"""Обработка одной генерации. Живёт только в worker, не в API-процессе."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy.orm.attributes import flag_modified

from nano_banana.config import settings
from nano_banana.db.models import Generation
from nano_banana.db.session import db_service
from nano_banana.error_log import save_error_to_file
from nano_banana.generation import runtime
from nano_banana.generation.keys import load_user_api_keys, select_key_for_model
from nano_banana.generation.references import materialize_reference_images
from nano_banana.providers.errors import (
    BANANALAB_EMPTY_DONE_RETRY_MESSAGE,
    BANANALAB_UPSTREAM_NO_IMAGE_EXHAUSTED_MESSAGE,
    BANANALAB_UPSTREAM_NO_IMAGE_RETRY_MESSAGE,
    humanize_api_error,
    is_bananalab_empty_done_message,
    is_bananalab_paused_message,
    is_bananalab_queue_timeout_message,
    is_bananalab_unavailable_message,
    is_bananalab_upstream_internal_error_message,
    is_bananalab_upstream_no_image_message,
    is_policy_block_error,
    upstream_no_image_retry_delay_seconds,
)
from nano_banana.providers.models import get_model_entry, get_provider_for_model, provider_label
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
        "enhance_requested": meta.get("enhance_requested"),
        "provider_job_id": meta.get("provider_job_id"),
        "provider_model": meta.get("provider_model"),
        "provider_cost_usd": meta.get("provider_cost_usd"),
        "gpt_rewrite_cost_usd": meta.get("gpt_rewrite_cost_usd"),
        "provider_phase": meta.get("provider_phase"),
        "status_detail": meta.get("status_detail"),
        "persist_pending": bool(meta.get("persist_pending")),
    }


def _provider_phase_labels(provider: Optional[str]) -> Dict[str, str]:
    name = {
        "bananalab": "Moonez",
        "openrouter": "OpenRouter",
        "replicate": "Replicate",
    }.get(provider or "", provider_label(provider) if provider else "Провайдер")
    return {
        "queued": f"Ждём {name} — задача в их очереди",
        "pending": f"Ждём {name} — задача в их очереди",
        "processing": f"{name} рисует…",
        "running": f"{name} рисует…",
        "in_progress": f"{name} рисует…",
        "started": f"{name} рисует…",
        "working": f"{name} рисует…",
        "done": f"{name} готов, сохраняем…",
        "completed": f"{name} готов, сохраняем…",
        "succeeded": f"{name} готов, сохраняем…",
        "success": f"{name} готов, сохраняем…",
        "finished": f"{name} готов, сохраняем…",
        "paused": f"{name} на паузе",
        "failed": f"{name} вернул ошибку",
        "error": f"{name} вернул ошибку",
    }


def _status_detail_for_phase(
    phase: str,
    *,
    elapsed: float = 0.0,
    provider: Optional[str] = None,
) -> str:
    labels = _provider_phase_labels(provider)
    name = labels.get("processing", "Провайдер").split(" ", 1)[0]
    label = labels.get((phase or "").strip().lower()) or f"{name}: {phase or '…'}"
    if elapsed >= 60:
        mins = int(elapsed // 60)
        return f"{label} ({mins} мин)"
    if elapsed >= 15:
        return f"{label} ({int(elapsed)} с)"
    return label


def _store_provider_trace(generation, result: Optional[dict]) -> None:
    if not result:
        return
    if not generation.generation_metadata:
        generation.generation_metadata = {}
    job_id = result.get("provider_job_id") or result.get("job_id")
    if job_id:
        generation.generation_metadata["provider_job_id"] = str(job_id)[:128]
    if result.get("provider_cost_usd") is not None:
        try:
            generation.generation_metadata["provider_cost_usd"] = float(result["provider_cost_usd"])
        except (TypeError, ValueError):
            pass
    if result.get("provider_model"):
        generation.generation_metadata["provider_model"] = str(result["provider_model"])[:120]
    flag_modified(generation, "generation_metadata")


def _build_resume_payload(generation: Generation, request_data: dict) -> Dict[str, Any]:
    metadata = generation.generation_metadata or {}
    return {
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
        "enhance_prompt": bool(request_data.get("enhance_prompt") or metadata.get("enhance_requested")),
    }


def _init_gpt_prompt_metadata(
    generation,
    session,
    prompt: str,
    *,
    rewrite_requested: bool,
    enhance_requested: bool,
) -> None:
    if not rewrite_requested and not enhance_requested:
        return
    if not generation.generation_metadata:
        generation.generation_metadata = {}
    if rewrite_requested:
        generation.generation_metadata["rewrite_requested"] = True
        generation.generation_metadata.setdefault("policy_gpt_attempts", [])
    if enhance_requested:
        generation.generation_metadata["enhance_requested"] = True
    generation.generation_metadata.setdefault("original_prompt", prompt)
    flag_modified(generation, "generation_metadata")
    session.commit()


def _add_gpt_rewrite_cost(generation, rewrite_result: dict) -> None:
    raw = rewrite_result.get("cost_usd")
    if raw is None:
        return
    try:
        amount = float(raw)
    except (TypeError, ValueError):
        return
    if amount < 0:
        return
    if not generation.generation_metadata:
        generation.generation_metadata = {}
    prev = float(generation.generation_metadata.get("gpt_rewrite_cost_usd") or 0)
    generation.generation_metadata["gpt_rewrite_cost_usd"] = round(prev + amount, 8)


def _try_upfront_gpt_enhance(generation, session, prompt: str, keys: dict) -> Optional[str]:
    openrouter_key = keys.get("openrouter")
    if not openrouter_key:
        if not generation.generation_metadata:
            generation.generation_metadata = {}
        generation.generation_metadata["rewrite_error"] = (
            "GPT улучшение промпта недоступно — добавьте ключ sk-or_ в настройках."
        )
        flag_modified(generation, "generation_metadata")
        session.commit()
        return None
    if not generation.generation_metadata:
        generation.generation_metadata = {}
    generation.generation_metadata["status_detail"] = "GPT улучшает промпт…"
    flag_modified(generation, "generation_metadata")
    session.commit()
    rewrite_result = OpenRouterService(api_key=openrouter_key).enhance_prompt(prompt)
    if rewrite_result.get("success") and rewrite_result.get("prompt"):
        enhanced = str(rewrite_result["prompt"]).strip()
        generation.generation_metadata["rewritten_prompt"] = enhanced
        generation.generation_metadata["rewrite_model"] = rewrite_result.get("model")
        _add_gpt_rewrite_cost(generation, rewrite_result)
        generation.generation_metadata.pop("rewrite_error", None)
        generation.generation_metadata.pop("status_detail", None)
        # Keep generation.prompt as the user's original; only metadata holds GPT text.
        flag_modified(generation, "generation_metadata")
        session.commit()
        return enhanced
    err = humanize_api_error(
        rewrite_result.get("error") or "GPT не смог улучшить промпт",
        provider="openrouter",
    )
    generation.generation_metadata["rewrite_error"] = err
    generation.generation_metadata.pop("status_detail", None)
    flag_modified(generation, "generation_metadata")
    session.commit()
    return None


def _try_policy_gpt_rewrite(generation, session, generation_id: int, prompt: str, block_reason: str, keys: dict) -> Optional[str]:
    openrouter_key = keys.get("openrouter")
    if not openrouter_key:
        return None
    if not generation.generation_metadata:
        generation.generation_metadata = {}
    attempts = list(generation.generation_metadata.get("policy_gpt_attempts") or [])
    attempt_n = len(attempts) + 1
    original_prompt = str(
        generation.generation_metadata.get("original_prompt") or generation.prompt or prompt or ""
    )
    rewrite_result = OpenRouterService(api_key=openrouter_key).rewrite_prompt_after_block(
        prompt,
        block_reason,
        attempt=attempt_n,
        original_prompt=original_prompt,
    )
    if rewrite_result.get("success") and rewrite_result.get("prompt"):
        attempts.append(
            {
                "attempt": attempt_n,
                "block_reason": (block_reason or "")[:500],
                "rewritten_prompt": rewrite_result.get("prompt"),
                "model": rewrite_result.get("model"),
                "cost_usd": rewrite_result.get("cost_usd"),
            }
        )
        generation.generation_metadata["policy_gpt_attempts"] = attempts
        generation.generation_metadata["rewritten_prompt"] = rewrite_result.get("prompt")
        generation.generation_metadata["rewrite_model"] = rewrite_result.get("model")
        _add_gpt_rewrite_cost(generation, rewrite_result)
        generation.generation_metadata.pop("rewrite_error", None)
        # Keep generation.prompt as the user's original; GPT text lives in metadata.
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
            if int(generation.user_id) != int(user_id):
                logger.error(
                    "[GENERATION] owner mismatch gen=%s job_user=%s owner=%s",
                    generation_id,
                    user_id,
                    generation.user_id,
                )
                return
            generation.status = "running"
            if not generation.generation_metadata:
                generation.generation_metadata = {}
            generation.generation_metadata["status_detail"] = "Подготовка генерации…"
            generation.generation_metadata["provider_phase"] = "preparing"
            flag_modified(generation, "generation_metadata")
            session.commit()
            queue.refresh_lock(generation_id)

            model_name = request_data.get("model_name") or generation.model_name or "nano-banana-pro"
            if not get_model_entry(model_name):
                _fail(generation, session, "Неизвестная модель")
                return

            api_key = select_key_for_model(generation.user_id, model_name)
            keys = load_user_api_keys(generation.user_id)
            provider = get_provider_for_model(model_name, keys)
            if not provider:
                _fail(generation, session, "Нет API ключа для этой модели")
                return
            provider_label_text = provider_label(provider)
            generation.generation_metadata["provider"] = provider
            if provider == "bananalab":
                generation.generation_metadata["status_detail"] = "Отправляем задачу в Moonez…"
            elif provider == "openrouter":
                generation.generation_metadata["status_detail"] = "Отправляем задачу в OpenRouter…"
            else:
                generation.generation_metadata["status_detail"] = f"Отправляем задачу ({provider_label_text})…"
            generation.generation_metadata["provider_phase"] = "submitting"
            flag_modified(generation, "generation_metadata")
            session.commit()

            try:
                if provider == "bananalab":
                    generation_service = BananalabService(api_key=api_key)
                elif provider == "openrouter":
                    generation_service = OpenRouterService(api_key=api_key)
                else:
                    generation_service = ReplicateService(api_token=api_key)
            except Exception as init_error:
                logger.error("[GENERATION] client init failed: %s", init_error)
                _fail(generation, session, f"Ошибка инициализации клиента ({provider_label_text})")
                return

            if provider == "bananalab" and model_name not in SUPPORTED_BANANALAB_FRONTEND_MODELS:
                logger.warning("[GENERATION] unsupported Moonez model '%s' ignored by API", model_name)

            prompt_for_generation = request_data.get("prompt") or ""
            rewrite_requested = bool(request_data.get("rewrite_prompt"))
            enhance_requested = bool(request_data.get("enhance_prompt"))
            _init_gpt_prompt_metadata(
                generation,
                session,
                prompt_for_generation,
                rewrite_requested=rewrite_requested,
                enhance_requested=enhance_requested,
            )
            max_policy_gpt = settings.MAX_POLICY_GPT_RETRIES if rewrite_requested else 0
            policy_gpt_used = 0
            result = None
            last_raw_error = ""
            try:
                meta = generation.generation_metadata or {}
                allowed_sources = list(meta.get("reference_image_urls") or [])
                src_path = getattr(generation, "result_path", None) or generation.result_url
                if src_path:
                    allowed_sources.append(src_path)
                provider_refs = materialize_reference_images(
                    get_storage(),
                    request_data.get("reference_images") or [],
                    allowed_sources=allowed_sources,
                )
            except Exception:
                logger.exception("[GENERATION] reference materialize failed gen=%s", generation_id)
                _fail(generation, session, "Не удалось прочитать референс.")
                return

            if enhance_requested:
                enhanced = _try_upfront_gpt_enhance(
                    generation, session, prompt_for_generation, keys
                )
                if enhanced and enhanced.strip() and enhanced.strip() != prompt_for_generation.strip():
                    prompt_for_generation = enhanced
                    logger.info(
                        "[GENERATION] %s prompt enhanced by GPT (%s chars)",
                        generation_id,
                        len(enhanced),
                    )
                else:
                    logger.warning(
                        "[GENERATION] %s enhance skipped/failed — using original prompt",
                        generation_id,
                    )

            def _on_provider_status(info: Dict[str, Any]) -> None:
                phase = str(info.get("phase") or "").strip().lower()
                job_id = info.get("job_id")
                elapsed = float(info.get("elapsed") or 0.0)
                if not generation.generation_metadata:
                    generation.generation_metadata = {}
                generation.generation_metadata["provider_phase"] = phase or "unknown"
                generation.generation_metadata["status_detail"] = _status_detail_for_phase(
                    phase, elapsed=elapsed, provider=provider
                )
                if job_id:
                    generation.generation_metadata["provider_job_id"] = str(job_id)[:128]
                flag_modified(generation, "generation_metadata")
                session.commit()
                queue.refresh_lock(generation_id)

            while True:
                queue.refresh_lock(generation_id)
                try:
                    gen_kwargs = {
                        "prompt": prompt_for_generation,
                        "negative_prompt": request_data.get("negative_prompt"),
                        "resolution": request_data.get("resolution", "1K"),
                        "aspect_ratio": request_data.get("aspect_ratio", "1:1"),
                        "guidance_scale": request_data.get("guidance_scale", 7.5),
                        "num_inference_steps": request_data.get("num_inference_steps", 50),
                        "seed": request_data.get("seed"),
                        "reference_images": provider_refs,
                        "model_name": model_name,
                    }
                    if provider == "bananalab":
                        gen_kwargs["on_status"] = _on_provider_status
                    result = generation_service.generate_image(**gen_kwargs)
                except Exception as gen_error:
                    error_msg = str(getattr(gen_error, "message", None) or gen_error)
                    full_error_msg = humanize_api_error(error_msg, provider=provider)
                    if not full_error_msg.startswith(
                        ("Banana Lab", "BananaHub", "OpenRouter", "Google", "Replicate", "Ошибка провайдера", "Сервис Banana", "Запрос не прошёл", "Moonez")
                    ):
                        full_error_msg = f"Ошибка генерации ({provider_label_text}): {full_error_msg}"
                    _fail(generation, session, full_error_msg)
                    return

                _store_provider_trace(generation, result)

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

                policy_hit = is_policy_block_error(last_raw_error) or is_policy_block_error(
                    error_message
                )
                if rewrite_requested and policy_hit and policy_gpt_used < max_policy_gpt:
                    if not keys.get("openrouter"):
                        if not generation.generation_metadata:
                            generation.generation_metadata = {}
                        generation.generation_metadata["rewrite_error"] = (
                            "GPT авто-переписывание недоступно — добавьте ключ sk-or_ в настройках."
                        )
                        flag_modified(generation, "generation_metadata")
                        session.commit()
                        break
                    logger.info(
                        "[GENERATION] %s policy block — GPT rewrite attempt %s/%s raw=%r",
                        generation_id,
                        policy_gpt_used + 1,
                        max_policy_gpt,
                        (last_raw_error or "")[:200],
                    )
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
                if not generation.generation_metadata:
                    generation.generation_metadata = {}

                try:
                    def _on_download_progress(done: int, total: int | None) -> None:
                        queue.refresh_lock(generation_id)

                    upload_result = persist_generation_result(
                        get_storage(),
                        result,
                        on_progress=_on_download_progress,
                    )
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
                generation.result_url = upload_result["path"]
                generation.result_path = upload_result["path"]
                generation.status = "completed"
                generation.completed_at = datetime.utcnow()
                generation.generation_metadata["provider"] = provider
                generation.generation_metadata.pop("status_detail", None)
                generation.generation_metadata.pop("provider_phase", None)
                flag_modified(generation, "generation_metadata")
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
            if provider == "bananalab" and (
                is_bananalab_upstream_internal_error_message(last_raw_error or error_message)
                or is_bananalab_queue_timeout_message(last_raw_error or error_message)
            ):
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
