"""HTTP: создать задачу генерации, список, статус. Сама генерация — в worker."""
from __future__ import annotations

import logging
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm.attributes import flag_modified

from nano_banana.auth import auth_service
from nano_banana.config import settings
from nano_banana.db.models import Generation, User
from nano_banana.db.session import db_service
from nano_banana.generation.cleanup import cleanup_old_generations
from nano_banana.generation.keys import load_user_api_keys, select_key_for_model
from nano_banana.generation.processor import MAX_GENERATION_RETRIES, get_fallback_model, rewrite_metadata_fields
from nano_banana.generation.references import store_reference_images
from nano_banana.providers.models import DEFAULT_MODEL_ID, MODEL_REGISTRY, get_provider_for_model
from nano_banana.queue.jobs import get_job_queue
from nano_banana.schemas import ImageGenerationRequest, ImageGenerationResponse, ImageResponse
from nano_banana.status.services import build_provider_status, build_public_service_status
from nano_banana.storage.s3 import MinioService
from nano_banana.tokens import TokenPayload

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/images", tags=["images"])
_minio: Optional[MinioService] = None


def _storage() -> MinioService:
    global _minio
    if _minio is None:
        _minio = MinioService()
    return _minio


@router.post("/generate", response_model=ImageGenerationResponse)
async def generate_image(
    request: ImageGenerationRequest,
    user: Annotated[TokenPayload, Depends(auth_service.get_current_user)],
):
    try:
        selected_model = request.model_name if request.model_name else DEFAULT_MODEL_ID
        keys = load_user_api_keys(user.user_id)
        model_provider = get_provider_for_model(selected_model, keys)
        if not model_provider:
            raise HTTPException(
                status_code=400,
                detail=f"Для модели «{selected_model}» нет подходящего API ключа. Добавьте ключ в настройках.",
            )
        api_key = select_key_for_model(user.user_id, request.model_name, request.api_key)
        _ = api_key

        with db_service.get_session() as session:
            active_count = (
                session.query(Generation)
                .filter(
                    Generation.user_id == user.user_id,
                    Generation.status.in_(["pending", "running", "paused"]),
                )
                .count()
            )
            if active_count >= settings.MAX_CONCURRENT_GENERATIONS:
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"Достигнут лимит одновременных генераций "
                        f"({settings.MAX_CONCURRENT_GENERATIONS}). Дождитесь завершения текущих."
                    ),
                )

        reference_image_urls: List[str] = []
        with db_service.get_session() as session:
            generation_metadata = {
                "model_name": selected_model,
                "provider": model_provider,
                "retry_count": 0,
                "max_retries": MAX_GENERATION_RETRIES,
            }
            generation = Generation(
                user_id=user.user_id,
                prompt=request.prompt,
                negative_prompt=request.negative_prompt,
                generation_mode=request.generation_mode,
                model_name=selected_model,
                resolution=request.resolution,
                aspect_ratio=request.aspect_ratio,
                guidance_scale=request.guidance_scale,
                num_inference_steps=request.num_inference_steps,
                seed=request.seed,
                status="pending",
                generation_metadata=generation_metadata,
            )
            session.add(generation)
            session.commit()
            session.refresh(generation)
            generation_id = generation.id

            if request.reference_images:
                reference_image_urls = store_reference_images(_storage(), request.reference_images)
                generation.generation_metadata["reference_images_count"] = len(request.reference_images)
                generation.generation_metadata["reference_image_urls"] = reference_image_urls
                flag_modified(generation, "generation_metadata")
                session.commit()

        payload = request.model_dump() if hasattr(request, "model_dump") else request.dict()
        if reference_image_urls:
            payload["reference_images"] = reference_image_urls
        get_job_queue().enqueue(generation_id, user.user_id, payload)
        return ImageGenerationResponse(
            status="pending",
            image_id=generation_id,
            message="Генерация добавлена в очередь",
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error("[GENERATION] create failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка создания задачи генерации: {e}") from e


@router.get("/list")
async def list_generations(
    request: Request,
    user: Annotated[TokenPayload, Depends(auth_service.get_current_user)],
):
    query_params = request.query_params
    try:
        limit_val = int(query_params.get("limit") or 50)
        if limit_val < 1 or limit_val > 100:
            limit_val = 50
    except (ValueError, TypeError):
        limit_val = 50
    try:
        offset_val = int(query_params.get("offset") or 0)
        if offset_val < 0:
            offset_val = 0
    except (ValueError, TypeError):
        offset_val = 0

    with db_service.get_session() as session:
        db_user = session.query(User).filter(User.id == user.user_id).first()
        if not db_user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        total_count = session.query(Generation).filter(Generation.user_id == user.user_id).count()
        generations = (
            session.query(Generation)
            .filter(Generation.user_id == user.user_id)
            .order_by(Generation.created_at.desc())
            .offset(offset_val)
            .limit(limit_val)
            .all()
        )
        result = []
        for gen in generations:
            meta = gen.generation_metadata or {}
            model_name = gen.model_name or meta.get("model_name") or "nano-banana-pro"
            item = ImageResponse(
                id=gen.id,
                user_id=gen.user_id,
                prompt=gen.prompt,
                negative_prompt=gen.negative_prompt,
                generation_mode=gen.generation_mode,
                resolution=gen.resolution,
                aspect_ratio=gen.aspect_ratio,
                result_url=gen.result_url,
                status=gen.status,
                created_at=gen.created_at,
                error_message=meta.get("error"),
                model_name=model_name,
                retry_count=int(meta.get("retry_count", 0) or 0),
                max_retries=int(meta.get("max_retries", MAX_GENERATION_RETRIES) or MAX_GENERATION_RETRIES),
                fallback_model=get_fallback_model(model_name),
                **rewrite_metadata_fields(meta),
            )
            data = item.model_dump() if hasattr(item, "model_dump") else item.dict()
            if data.get("created_at"):
                data["created_at"] = data["created_at"].isoformat()
            result.append(data)
        return JSONResponse(
            content={
                "generations": result,
                "meta": {
                    "total": total_count,
                    "shown": len(result),
                    "limit": limit_val,
                    "offset": offset_val,
                    "storage_info": {
                        "retention_days": 7,
                        "message": "Изображения хранятся 7 дней, затем автоматически удаляются",
                    },
                },
            }
        )


@router.get("/models")
async def get_available_models(user: Annotated[TokenPayload, Depends(auth_service.get_current_user)]):
    _ = user
    models = {}
    for key, entry in MODEL_REGISTRY.items():
        models[key] = {
            "display_name": entry["display_name"],
            "description": entry["description"],
            "name": entry.get("replicate_slug") or entry.get("openrouter_slug") or key,
            "providers": entry.get("providers", []),
            "color": entry.get("color", "replicate"),
            "params_profile": entry.get("params_profile", "nano"),
            "group": entry.get("group") or entry.get("color", "replicate"),
        }
    return {
        "models": models,
        "default_model": DEFAULT_MODEL_ID,
        "bananalab_key_prefix": "bh_",
        "bananalab_key_prefix_legacy": "nb_",
        "replicate_key_prefix_hint": "r8_",
        "openrouter_key_prefix_hint": "sk-or",
        "provider_colors": {
            "bananalab": "#f59e0b",
            "replicate": "#3b82f6",
            "openrouter": "#10b981",
        },
    }


@router.get("/service-status")
@router.get("/bananahub-health")
async def get_service_status(
    user: Annotated[Optional[TokenPayload], Depends(auth_service.get_optional_user)] = None,
):
    user_id = user.user_id if user else None
    return build_public_service_status(user_id=user_id)


@router.get("/provider-status")
async def get_provider_status(
    user: Annotated[TokenPayload, Depends(auth_service.get_current_user)],
    model_name: Optional[str] = None,
):
    return build_provider_status(user.user_id, model_name)


@router.get("/{generation_id}")
async def get_generation_full(
    generation_id: int,
    user: Annotated[TokenPayload, Depends(auth_service.get_current_user)],
):
    with db_service.get_session() as session:
        generation = session.query(Generation).filter(
            Generation.id == generation_id,
            Generation.user_id == user.user_id,
        ).first()
        if not generation:
            raise HTTPException(status_code=404, detail="Генерация не найдена")
        metadata = generation.generation_metadata or {}
        model_name = generation.model_name or metadata.get("model_name", "nano-banana-pro")
        return {
            "id": generation.id,
            "prompt": generation.prompt,
            "negative_prompt": generation.negative_prompt,
            "generation_mode": generation.generation_mode,
            "resolution": generation.resolution,
            "aspect_ratio": generation.aspect_ratio,
            "guidance_scale": generation.guidance_scale,
            "num_inference_steps": generation.num_inference_steps,
            "seed": generation.seed,
            "model_name": model_name,
            "reference_images": metadata.get("reference_image_urls", []),
            "result_url": generation.result_url,
            "status": generation.status,
            "error_message": metadata.get("error"),
            **rewrite_metadata_fields(metadata),
        }


@router.delete("/{generation_id}")
async def delete_generation(
    generation_id: int,
    user: Annotated[TokenPayload, Depends(auth_service.get_current_user)],
):
    with db_service.get_session() as session:
        generation = session.query(Generation).filter(
            Generation.id == generation_id,
            Generation.user_id == user.user_id,
        ).first()
        if not generation:
            raise HTTPException(status_code=404, detail="Генерация не найдена")
        if generation.result_path:
            _storage().delete_image(generation.result_path)
        session.delete(generation)
        session.commit()
        return {"message": "Генерация удалена"}


@router.post("/cleanup")
async def cleanup_endpoint(user: Annotated[TokenPayload, Depends(auth_service.get_current_user)]):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Доступ запрещен")
    return cleanup_old_generations(_storage())
