"""Клиентские URL картинок: только cookie-прокси на MinIO, без Moonez CDN в браузере."""
from __future__ import annotations

from typing import List, Optional


def generation_file_url(generation_id: int) -> str:
    return f"/api/v1/images/{int(generation_id)}/file"


def generation_reference_url(generation_id: int, index: int) -> str:
    return f"/api/v1/images/{int(generation_id)}/reference/{int(index)}"


def _is_storage_object_key(value: Optional[str]) -> bool:
    """True for MinIO object keys; false for http(s) /api paths."""
    if not value or not isinstance(value, str):
        return False
    v = value.strip()
    if not v:
        return False
    if v.startswith(("/api/", "http://", "https://")):
        return False
    return True


def client_result_url(generation) -> Optional[str]:
    """Gallery/lightbox URL only when the file is already in our MinIO.

    Moonez CDN (cdn.rendergrid.io) is never exposed to the browser — some RU
    ISPs reset that host. Until persist finishes, return None (UI shows spinner).
    """
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
