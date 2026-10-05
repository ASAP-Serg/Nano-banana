"""Клиентские URL картинок: только cookie-прокси, без presign в браузер."""
from __future__ import annotations

from typing import List, Optional


def generation_file_url(generation_id: int) -> str:
    return f"/api/v1/images/{int(generation_id)}/file"


def generation_reference_url(generation_id: int, index: int) -> str:
    return f"/api/v1/images/{int(generation_id)}/reference/{int(index)}"


def client_result_url(generation) -> Optional[str]:
    if getattr(generation, "result_path", None) or getattr(generation, "result_url", None):
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
