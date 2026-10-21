"""Автоочистка старых генераций и сброс зависших jobs."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import List, Optional

from nano_banana.config import settings
from nano_banana.db.models import Generation
from nano_banana.db.session import db_service
from nano_banana.queue.jobs import get_job_queue
from nano_banana.storage.s3 import MinioService

logger = logging.getLogger(__name__)
RETENTION_DAYS = 7


def _extract_storage_path(url: str, bucket: str) -> Optional[str]:
    if not url:
        return None
    if url.startswith("images/"):
        path = url.split("?", 1)[0]
        if ".." in path or path.startswith("/") or "\\" in path:
            return None
        return path
    marker = f"/{bucket}/"
    idx = url.find(marker)
    if idx == -1:
        return None
    return url[idx + len(marker) :]


def delete_generation_assets(minio: MinioService, generation: Generation) -> list[str]:
    """Удаляет result + reference objects этой генерации из MinIO. Возвращает удалённые пути."""
    deleted: List[str] = []
    result = getattr(generation, "result_path", None) or getattr(generation, "result_url", None)
    if result:
        path = minio.extract_object_path(result) or _extract_storage_path(str(result), settings.MINIO_BUCKET)
        if path and minio.delete_image(path):
            deleted.append(path)
    meta = generation.generation_metadata or {}
    for url in meta.get("reference_image_urls") or []:
        if not url:
            continue
        path = minio.extract_object_path(url) or _extract_storage_path(str(url), settings.MINIO_BUCKET)
        if path and minio.delete_image(path):
            deleted.append(path)
    return deleted


def cleanup_old_generations(minio: MinioService, retention_days: int = RETENTION_DAYS) -> dict:
    cutoff = datetime.utcnow() - timedelta(days=retention_days)
    deleted_count = 0
    deleted_files: List[str] = []
    with db_service.get_session() as session:
        old_generations: List[Generation] = (
            session.query(Generation).filter(Generation.created_at < cutoff).all()
        )
        for gen in old_generations:
            deleted_files.extend(delete_generation_assets(minio, gen))
            session.delete(gen)
            deleted_count += 1
    logger.info("[CLEANUP] deleted generations=%s files=%s", deleted_count, len(deleted_files))
    return {
        "deleted_generations": deleted_count,
        "deleted_files": deleted_files,
        "retention_days": retention_days,
    }


def reclaim_unlocked_jobs() -> int:
    """Вернуть в очередь running/pending/paused без живого lock (рестарт воркера)."""
    queue = get_job_queue()
    requeued = 0
    with db_service.get_session() as session:
        rows = (
            session.query(Generation)
            .filter(Generation.status.in_(["pending", "running", "paused"]))
            .all()
        )
        for gen in rows:
            if queue.has_lock(gen.id):
                continue
            metadata = gen.generation_metadata or {}
            request_data = metadata.get("paused_request_data") or {
                "prompt": gen.prompt,
                "negative_prompt": gen.negative_prompt,
                "resolution": gen.resolution,
                "aspect_ratio": gen.aspect_ratio,
                "guidance_scale": gen.guidance_scale,
                "num_inference_steps": gen.num_inference_steps,
                "seed": gen.seed,
                "model_name": gen.model_name or metadata.get("model_name"),
                "reference_images": metadata.get("reference_image_urls") or [],
                "rewrite_prompt": bool(metadata.get("rewrite_requested")),
            }
            if gen.status == "running":
                gen.status = "pending"
            queue.enqueue(gen.id, gen.user_id, request_data, delay_seconds=0)
            requeued += 1
        session.commit()
    if requeued:
        logger.info("[WORKER] requeued unlocked jobs: %s", requeued)
    return requeued


def fail_stuck_generations(minutes: Optional[int] = None) -> int:
    stuck_minutes = minutes or settings.STUCK_GENERATION_MINUTES
    cutoff = datetime.utcnow() - timedelta(minutes=stuck_minutes)
    fixed = 0
    with db_service.get_session() as session:
        stuck = (
            session.query(Generation)
            .filter(Generation.created_at < cutoff)
            .filter(Generation.status.in_(["running", "pending"]))
            .all()
        )
        for gen in stuck:
            gen.status = "failed"
            gen.completed_at = datetime.utcnow()
            if not gen.generation_metadata:
                gen.generation_metadata = {}
            gen.generation_metadata["error"] = (
                f"Генерация была автоматически помечена как неудачная, "
                f"так как выполнялась дольше {stuck_minutes} минут без завершения."
            )
            from sqlalchemy.orm.attributes import flag_modified

            flag_modified(gen, "generation_metadata")
            fixed += 1
        session.commit()
    return fixed
