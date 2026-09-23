"""Обработка одной генерации. Живёт только в worker, не в API-процессе."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy.orm.attributes import flag_modified

from nano_banana.config import settings
from nano_banana.crypto import CryptoService
from nano_banana.db.models import Generation
from nano_banana.db.session import db_service
from nano_banana.error_log import save_error_to_file
from nano_banana.generation import runtime
from nano_banana.generation.keys import load_user_api_keys, select_key_for_model
from nano_banana.providers.detect import infer_image_api_provider
from nano_banana.providers.errors import (
    BANANALAB_EMPTY_DONE_RETRY_MESSAGE,
    BANANALAB_UPSTREAM_NO_IMAGE_EXHAUSTED_MESSAGE,
    BANANALAB_UPSTREAM_NO_IMAGE_RETRY_MESSAGE,
    humanize_api_error,
    is_bananalab_empty_done_message,
    is_bananalab_paused_message,
    is_bananalab_unavailable_message,
    is_bananalab_upstream_internal_error_message,
    is_bananalab_upstream_no_image_message,
    is_policy_block_error,
    upstream_no_image_retry_delay_seconds,
)
from nano_banana.providers.models import get_provider_for_model, provider_label
from nano_banana.providers.moonez import BananalabService, SUPPORTED_BANANALAB_FRONTEND_MODELS
from nano_banana.providers.openrouter import OpenRouterService
from nano_banana.providers.replicate import ReplicateService
from nano_banana.queue.jobs import get_job_queue
from nano_banana.storage.results import persist_generation_result
from nano_banana.storage.s3 import MinioService

logger = logging.getLogger(__name__)

MAX_GENERATION_RETRIES = 5
PAUSED_RETRY_DELAY_SECONDS = 30
FALLBACK_MODEL_BY_MODEL: Dict[str, str] = {}

_storage: Optional[MinioService] = None


def get_storage() -> MinioService:
    global _storage
    if _storage is None:
        _storage = MinioService()
    return _storage


def get_fallback_model(model_name: Optional[str]) -> Optional[str]:
    if not model_name:
        return None
    return FALLBACK_MODEL_BY_MODEL.get(model_name)


def rewrite_metadata_fields(metadata: Optional[dict]) -> dict:
    meta = metadata or {}
    return {
        "provider": meta.get("provider"),
        "original_prompt": meta.get("original_prompt"),
        "sanitized_prompt": meta.get("sanitized_prompt"),
        "sanitize_replacements": meta.get("sanitize_replacements"),
        "rewritten_prompt": meta.get("rewritten_prompt"),
        "rewrite_model": meta.get("rewrite_model"),
        "rewrite_error": meta.get("rewrite_error"),
        "policy_gpt_attempts": meta.get("policy_gpt_attempts"),
        "rewrite_requested": meta.get("rewrite_requested"),
    }


def _encrypt_api_key(api_key: str) -> str:
    return CryptoService.encrypt(api_key) if api_key else ""


def _decrypt_api_key(token: Optional[str]) -> Optional[str]:
    return CryptoService.decrypt(token) if token else None


def _build_resume_payload(generation: Generation, request_data: dict) -> Dict[str, Any]:
    metadata = generation.generation_metadata or {}
    plain_api_key = request_data.get("api_key")
    encrypted = request_data.get("api_key_encrypted") or ""
    if plain_api_key and not encrypted:
        encrypted = _encrypt_api_key(plain_api_key)
    return {
        # Только шифрованная форма — plaintext api_key не сохраняем.
        "api_key_encrypted": encrypted,
        "prompt": request_data.get("prompt") or generation.prompt,
        "negative_prompt": request_data.get("negative_prompt") or generation.negative_prompt,
        "resolution": request_data.get("resolution") or generation.resolution,
        "aspect_ratio": request_data.get("aspect_ratio") or generation.aspect_ratio,
        "guidance_scale": request_data.get("guidance_scale") or generation.guidance_scale,
        "num_inference_steps": request_data.get("num_inference_steps") or generation.num_inference_steps,
        "seed": request_data.get("seed") if request_data.get("seed") is not None else generation.seed,
        "model_name": request_data.get("model_name") or generation.model_name or metadata.get("model_name"),
        "reference_images": request_data.get("reference_images") or metadata.get("reference_image_urls") or [],
        "rewrite_prompt": bool(request_data.get("rewrite_prompt") or metadata.get("rewrite_requested")),
    }


def _init_policy_rewrite_metadata(generation, session, prompt: str, rewrite_requested: bool) -> None:
    if not rewrite_requested:
        return
    if not generation.generation_metadata:
        generation.generation_metadata = {}
    generation.generation_metadata["rewrite_requested"] = True
    generation.generation_metadata.setdefault("original_prompt", prompt)
    generation.generation_metadata.setdefault("policy_gpt_attempts", [])
    flag_modified(generation, "generation_metadata")
    session.commit()


def _try_policy_gpt_rewrite(generation, session, generation_id: int, prompt: str, block_reason: str, keys: dict) -> Optional[str]:
    openrouter_key = keys.get("openrouter")
    if not openrouter_key:
        return None
    rewrite_result = OpenRouterService(api_key=openrouter_key).rewrite_prompt_after_block(prompt, block_reason)
    if rewrite_result.get("success") and rewrite_result.get("prompt"):
        if not generation.generation_metadata:
            generation.generation_metadata = {}
        attempts = list(generation.generation_metadata.get("policy_gpt_attempts") or [])
        attempts.append(
            {
                "attempt": len(attempts) + 1,
                "block_reason": (block_reason or "")[:500],
                "rewritten_prompt": rewrite_result.get("prompt"),
                "model": rewrite_result.get("model"),
            }
        )
        generation.generation_metadata["policy_gpt_attempts"] = attempts
        generation.generation_metadata["rewritten_prompt"] = rewrite_result.get("prompt")
        generation.generation_metadata["rewrite_model"] = rewrite_result.get("model")
        generation.generation_metadata.pop("rewrite_error", None)
        flag_modified(generation, "generation_metadata")
        session.commit()
        return rewrite_result["prompt"]
    err = humanize_api_error(rewrite_result.get("error") or "GPT не смог переписать промпт", provider="openrouter")
    if not generation.generation_metadata:
        generation.generation_metadata = {}
    generation.generation_metadata["rewrite_error"] = err
    flag_modified(generation, "generation_metadata")
    session.commit()
    return None


def _fail(generation, session, message: str) -> None:
    generation.status = "failed"
    generation.completed_at = datetime.utcnow()
    if not generation.generation_metadata:
        generation.generation_metadata = {}
    generation.generation_metadata["error"] = message
    generation.generation_metadata.pop("paused_request_data", None)
    flag_modified(generation, "generation_metadata")
    session.commit()


def process_generation(generation_id: int, user_id: int, request_data: dict) -> None:
    queue = get_job_queue()
    if not queue.acquire_lock(generation_id):
        logger.info("[GENERATION] skip gen=%s — lock held", generation_id)
        return
    started_at = datetime.utcnow()
    try:
        _process_locked(generation_id, user_id, request_data, started_at)
    finally:
        queue.release_lock(generation_id)


def _process_locked(generation_id: int, user_id: int, request_data: dict, started_at: datetime) -> None:
    queue = get_job_queue()
    try:
        with db_service.get_session() as session:
            generation = session.query(Generation).filter(Generation.id == generation_id).first()
            if not generation:
                logger.error("[GENERATION] %s not found", generation_id)
                return
            generation.status = "running"
            session.commit()
            queue.refresh_lock(generation_id)

            api_key_from_request = request_data.get("api_key")
            if (not api_key_from_request or not str(api_key_from_request).strip()) and request_data.get("api_key_encrypted"):
                api_key_from_request = _decrypt_api_key(request_data.get("api_key_encrypted"))
            api_key = select_key_for_model(user_id, request_data.get("model_name"), api_key_from_request)
            keys = load_user_api_keys(user_id)
            provider = get_provider_for_model(request_data.get("model_name"), keys) or infer_image_api_provider(api_key)
            provider_label_text = provider_label(provider)

            try:
                if provider == "bananalab":
                    generation_service = BananalabService(api_key=api_key)
                elif provider == "openrouter":
                    generation_service = OpenRouterService(api_key=api_key)
                else:
                    generation_service = ReplicateService(api_token=api_key)
            except Exception as init_error:
                _fail(generation, session, f"Ошибка инициализации клиента ({provider_label_text}): {init_error}")
                return

            model_name = request_data.get("model_name") or generation.model_name or "nano-banana-pro"
            if provider == "bananalab" and model_name not in SUPPORTED_BANANALAB_FRONTEND_MODELS:
                logger.warning("[GENERATION] unsupported Moonez model '%s' ignored by API", model_name)

            prompt_for_generation = request_data.get("prompt") or ""
            rewrite_requested = bool(request_data.get("rewrite_prompt"))
            _init_policy_rewrite_metadata(generation, session, prompt_for_generation, rewrite_requested)
            max_policy_gpt = settings.MAX_POLICY_GPT_RETRIES if rewrite_requested else 0
            policy_gpt_used = 0
            result = None
            last_raw_error = ""

            while True:
                queue.refresh_lock(generation_id)
                try:
                    result = generation_service.generate_image(
                        prompt=prompt_for_generation,
                        negative_prompt=request_data.get("negative_prompt"),
                        resolution=request_data.get("resolution", "1K"),
                        aspect_ratio=request_data.get("aspect_ratio", "1:1"),
                        guidance_scale=request_data.get("guidance_scale", 7.5),
                        num_inference_steps=request_data.get("num_inference_steps", 50),
                        seed=request_data.get("seed"),
                        reference_images=request_data.get("reference_images"),
                        model_name=model_name,
                    )
                except Exception as gen_error:
                    error_msg = str(getattr(gen_error, "message", None) or gen_error)
                    full_error_msg = humanize_api_error(error_msg, provider=provider)
                    if not full_error_msg.startswith(
                        ("Banana Lab", "BananaHub", "OpenRouter", "Google", "Replicate", "Ошибка провайдера", "Сервис Banana", "Запрос не прошёл", "Moonez")
                    ):
                        full_error_msg = f"Ошибка генерации ({provider_label_text}): {full_error_msg}"
                    _fail(generation, session, full_error_msg)
                    return

                if result.get("success"):
                    break

                error_message = result.get("error") or result.get("message") or result.get("detail") or "Неизвестная ошибка генерации"
                if not isinstance(error_message, str):
                    error_message = str(error_message)
                last_raw_error = error_message
                error_message = humanize_api_error(error_message, provider=provider)

                if result.get("unavailable") or is_bananalab_unavailable_message(error_message):
                    break
                if result.get("paused") or is_bananalab_paused_message(error_message):
                    break

                if rewrite_requested and is_policy_block_error(last_raw_error) and policy_gpt_used < max_policy_gpt:
                    if not keys.get("openrouter"):
                        if not generation.generation_metadata:
                            generation.generation_metadata = {}
                        generation.generation_metadata["rewrite_error"] = (
                            "GPT авто-переписывание недоступно — добавьте ключ sk-or_ в настройках."
                        )
                        flag_modified(generation, "generation_metadata")
                        session.commit()
                        break
                    new_prompt = _try_policy_gpt_rewrite(
                        generation, session, generation_id, prompt_for_generation, error_message, keys
                    )
                    if new_prompt and new_prompt.strip() != prompt_for_generation.strip():
                        prompt_for_generation = new_prompt
                        policy_gpt_used += 1
                        continue
                    break
                break

            if result and result.get("success"):
                if provider == "bananalab":
                    runtime.mark_success()
                if generation.generation_metadata and generation.generation_metadata.get("paused_request_data"):
                    generation.generation_metadata.pop("paused_request_data", None)
                try:
                    upload_result = persist_generation_result(get_storage(), result)
                except Exception:
                    logger.exception("[GENERATION] persist failed gen=%s", generation_id)
                    _fail(generation, session, "Не удалось сохранить изображение в хранилище.")
                    return
                if not upload_result:
                    _fail(
                        generation,
                        session,
                        "Не удалось сохранить изображение в хранилище. "
                        "Сеть или сервис провайдера могли быть недоступны — повторите генерацию.",
                    )
                    return
                generation.result_url = upload_result["url"]
                generation.result_path = upload_result["path"]
                generation.status = "completed"
                generation.completed_at = datetime.utcnow()
                session.commit()
                logger.info(
                    "[GENERATION] %s completed in %.1fs",
                    generation_id,
                    (generation.completed_at - started_at).total_seconds(),
                )
                return

            if not generation.generation_metadata:
                generation.generation_metadata = {}
            error_message = (result or {}).get("error") or "Неизвестная ошибка генерации"
            if not isinstance(error_message, str):
                error_message = str(error_message)
            error_message = humanize_api_error(error_message, provider=provider)

            if (result or {}).get("unavailable") or is_bananalab_unavailable_message(error_message):
                generation.generation_metadata["error"] = error_message
                generation.generation_metadata.pop("paused_request_data", None)
                if provider == "bananalab":
                    runtime.mark_unavailable(error_message)
                _fail(generation, session, error_message)
                return

            if (result or {}).get("paused") or is_bananalab_paused_message(error_message):
                generation.status = "paused"
                generation.completed_at = None
                paused_payload = _build_resume_payload(generation, request_data)
                generation.generation_metadata["error"] = error_message
                generation.generation_metadata["paused_at"] = datetime.utcnow().isoformat()
                generation.generation_metadata["paused_request_data"] = paused_payload
                if provider == "bananalab":
                    runtime.mark_paused(error_message)
                flag_modified(generation, "generation_metadata")
                session.commit()
                queue.enqueue(generation_id, user_id, paused_payload, delay_seconds=PAUSED_RETRY_DELAY_SECONDS)
                return

            lower_err = error_message.lower()
            service_retryable = bool((result or {}).get("retryable"))
            policy_block = is_policy_block_error(last_raw_error) or is_policy_block_error(error_message)
            upstream_no_image = (not policy_block) and is_bananalab_upstream_no_image_message(last_raw_error or error_message)
            empty_done = (not policy_block) and (
                bool((result or {}).get("empty_done")) or is_bananalab_empty_done_message(last_raw_error or error_message)
            )
            is_retryable = service_retryable or upstream_no_image or empty_done or (
                "e003" in lower_err
                or "high demand" in lower_err
                or "429" in lower_err
                or "ratelimit" in lower_err
                or "временно недоступен" in lower_err
                or "521" in lower_err
                or "522" in lower_err
                or "524" in lower_err
            )
            current_retries = generation.generation_metadata.get("retry_count", 0)
            max_retries_for_error = (
                settings.BANANALAB_UPSTREAM_NO_IMAGE_MAX_RETRIES
                if (upstream_no_image or empty_done)
                else MAX_GENERATION_RETRIES
            )
            if is_retryable and current_retries < max_retries_for_error:
                generation.generation_metadata["retry_count"] = current_retries + 1
                generation.generation_metadata["max_retries"] = max_retries_for_error
                generation.status = "pending"
                generation.completed_at = None
                if upstream_no_image:
                    generation.generation_metadata["error"] = BANANALAB_UPSTREAM_NO_IMAGE_RETRY_MESSAGE
                elif empty_done:
                    generation.generation_metadata["error"] = BANANALAB_EMPTY_DONE_RETRY_MESSAGE
                flag_modified(generation, "generation_metadata")
                session.commit()
                retry_delay = (
                    upstream_no_image_retry_delay_seconds(
                        current_retries,
                        settings.BANANALAB_UPSTREAM_NO_IMAGE_RETRY_BASE_DELAY_SECONDS,
                    )
                    if (upstream_no_image or empty_done)
                    else 0
                )
                queue.enqueue(generation_id, user_id, request_data, delay_seconds=retry_delay)
                return

            if upstream_no_image:
                error_message = BANANALAB_UPSTREAM_NO_IMAGE_EXHAUSTED_MESSAGE
                generation.generation_metadata["error_code"] = "upstream_no_image"
            if len(error_message) > 2000:
                error_message = error_message[:2000] + "... (сообщение обрезано)"
            if provider == "bananalab" and is_bananalab_upstream_internal_error_message(last_raw_error or error_message):
                runtime.mark_upstream_degraded(last_raw_error or error_message)
            save_error_to_file(
                {
                    "type": "generation_error",
                    "generation_id": generation_id,
                    "user_id": user_id,
                    "prompt": request_data.get("prompt"),
                    "error": error_message,
                    "status": "failed",
                }
            )
            _fail(generation, session, error_message)
    except Exception as exc:
        logger.error("[GENERATION] %s crashed: %s", generation_id, exc, exc_info=True)
        save_error_to_file(
            {
                "type": "generation_exception",
                "generation_id": generation_id,
                "user_id": user_id,
                "error": str(exc),
                "error_type": type(exc).__name__,
            }
        )
        with db_service.get_session() as session:
            generation = session.query(Generation).filter(Generation.id == generation_id).first()
            if generation:
                meta = generation.generation_metadata or {}
                _fail(generation, session, humanize_api_error(str(exc), provider=meta.get("provider")))
