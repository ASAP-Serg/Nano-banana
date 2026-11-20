"""Клиентские URL картинок: только наш /file proxy (MinIO или server-side CDN fetch)."""
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
    """URL для галереи: всегда наш /file, если есть MinIO-ключ или CDN URL провайдера.

    Браузер никогда не ходит на cdn.rendergrid.io напрямую — /file отдаёт байты
    из MinIO или скачивает CDN на сервере.
    """
    path = getattr(generation, "result_path", None) or getattr(generation, "result_url", None)
    if _is_storage_object_key(path):
        return generation_file_url(generation.id)
    meta = getattr(generation, "generation_metadata", None) or {}
    provider_url = meta.get("provider_image_url")
    if isinstance(provider_url, str) and provider_url.startswith(("https://", "http://")):
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
