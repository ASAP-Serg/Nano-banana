"""Клиентские URL картинок: MinIO через /file, иначе прямой CDN провайдера."""
from __future__ import annotations

from typing import List, Optional
from urllib.parse import urlparse

# Браузер может ходить сюда напрямую (CSP + isSafeMediaUrl). Нужно для VPN/зарубежных
# ISP: RU VPS часто не может докачать Moonez CDN в MinIO.
_CLIENT_CDN_HOST_SUFFIXES = (
    "rendergrid.io",
    "moonez.ai",
    "replicate.delivery",
    "replicate.com",
    "googleusercontent.com",
    "storage.googleapis.com",
)


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


def _client_safe_cdn_url(value: Optional[str]) -> Optional[str]:
    if not value or not isinstance(value, str):
        return None
    url = value.strip()
    if not url.startswith("https://") or ".." in url:
        return None
    try:
        host = (urlparse(url).hostname or "").lower().rstrip(".")
    except Exception:
        return None
    if not host:
        return None
    for suffix in _CLIENT_CDN_HOST_SUFFIXES:
        if host == suffix or host.endswith("." + suffix):
            return url
    return None


def client_result_url(generation) -> Optional[str]:
    """URL для галереи: MinIO → наш /file; иначе прямой HTTPS CDN провайдера.

    Пока VPS не может стабильно положить файл в MinIO, браузер (с VPN) должен
    ходить на CDN сам — не через 302/прокси с RU-сервера.
    """
    path = getattr(generation, "result_path", None) or getattr(generation, "result_url", None)
    if _is_storage_object_key(path):
        return generation_file_url(generation.id)
    meta = getattr(generation, "generation_metadata", None) or {}
    for candidate in (meta.get("provider_image_url") if isinstance(meta, dict) else None, path):
        cdn = _client_safe_cdn_url(candidate if isinstance(candidate, str) else None)
        if cdn:
            return cdn
    return None


def client_reference_urls(generation) -> List[str]:
    metadata = getattr(generation, "generation_metadata", None) or {}
    stored = metadata.get("reference_image_urls") or []
    return [
        generation_reference_url(generation.id, index)
        for index, item in enumerate(stored)
        if item
    ]
