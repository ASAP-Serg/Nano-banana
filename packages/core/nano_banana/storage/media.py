"""Клиентские URL картинок: только MinIO через /file (без прямого CDN провайдера)."""
from __future__ import annotations

from typing import List, Optional


def generation_file_url(generation_id: int) -> str:
    return f"/api/v1/images/{int(generation_id)}/file"


def generation_reference_url(generation_id: int, index: int) -> str:
    return f"/api/v1/images/{int(generation_id)}/reference/{int(index)}"


def _is_storage_object_key(value: Optional[str]) -> bool:
    if not value or not isinstance(value, str):
        return False
    v = value.strip()
    if not v:
        return False
    if v.startswith(("/api/", "http://", "https://")):
        return False
    return True


def client_result_url(generation) -> Optional[str]:
    """URL для галереи: только объект в MinIO → наш /file."""
    path = getattr(generation, "result_path", None) or getattr(generation, "result_url", None)
    if _is_storage_object_key(path):
        return generation_file_url(generation.id)
    return None


def client_reference_urls(generation) -> List[str]:
    metadata = getattr(generation, "generation_metadata", None) or {}
    stored = metadata.get("reference_image_urls") or []
    return [
        generation_reference_url(generation.id, index)
        for index, item in enumerate(stored)
        if item
    ]
