"""Общие проверки безопасности для Nano-Banana."""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from app.config import Settings


def generate_storage_object_name(subfolder: str, ext: str = "jpg") -> str:
    """Непредсказуемое имя объекта в MinIO (для публичного шаринга по ссылке)."""
    safe_ext = (ext or "jpg").lstrip(".").lower()[:8]
    folder = subfolder.strip("/")
    return f"images/{folder}/{uuid.uuid4().hex}.{safe_ext}"


def _host_aliases(netloc: str) -> set[str]:
    """localhost ↔ 127.0.0.1 — чтобы референсы из галереи работали в dev."""
    netloc = (netloc or "").lower()
    aliases = {netloc} if netloc else set()
    host, _, port = netloc.partition(":")
    if host == "localhost":
        aliases.add(f"127.0.0.1{':' + port if port else ''}")
    if host == "127.0.0.1":
        aliases.add(f"localhost{':' + port if port else ''}")
    return aliases


def _public_url_hosts(settings: "Settings") -> set[str]:
    hosts: set[str] = set()
    for raw in (settings.MINIO_PUBLIC_URL, getattr(settings, "API_URL", "")):
        if not raw:
            continue
        parsed = urlparse(raw.strip())
        if parsed.netloc:
            hosts.update(_host_aliases(parsed.netloc))
    extra = getattr(settings, "SECURITY_ALLOWED_REF_URL_HOSTS", "") or ""
    for part in extra.split(","):
        part = part.strip().lower()
        if part:
            hosts.update(_host_aliases(part))
    return hosts


def is_allowed_reference_url(url: str, settings: "Settings") -> bool:
    """
    Разрешаем только ссылки на объекты в нашем MinIO bucket.
    Блокирует SSRF через произвольные http(s) URL в reference_images.
    """
    if not url or not isinstance(url, str):
        return False
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        return False

    parsed = urlparse(url)
    if parsed.netloc.lower() not in _public_url_hosts(settings):
        return False

    bucket_marker = f"/{settings.MINIO_BUCKET}/"
    if bucket_marker not in url:
        return False

    object_path = url.split(bucket_marker, 1)[1].split("?", 1)[0]
    if not object_path or object_path.startswith("..") or ".." in object_path:
        return False
    # results/, references/ и legacy ref_* — всё из нашего хранилища
    return object_path.startswith("images/")
