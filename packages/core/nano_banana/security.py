"""Общие проверки безопасности для Nano-Banana."""
from __future__ import annotations

import ipaddress
import socket
import uuid
from typing import TYPE_CHECKING, Optional, Set
from urllib.parse import urlparse

if TYPE_CHECKING:
    from nano_banana.config import Settings

_DEFAULT_OUTBOUND_IMAGE_HOST_SUFFIXES = (
    "replicate.delivery",
    "replicate.com",
    "pbxt.replicate.delivery",
    "moonez.ai",
    "cloudflare.com",
    "r2.dev",
    "amazonaws.com",
    "googleusercontent.com",
    "storage.googleapis.com",
)


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
    return object_path.startswith("images/")


def _is_private_ip(ip: ipaddress._BaseAddress) -> bool:
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _hostname_resolves_to_private(hostname: str) -> bool:
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return True
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if _is_private_ip(ip):
            return True
    return False


def _outbound_host_allowed(hostname: str, settings: "Settings") -> bool:
    host = (hostname or "").lower().rstrip(".")
    if not host:
        return False
    for allowed in _public_url_hosts(settings):
        allowed_host = allowed.split(":")[0]
        if host == allowed_host or host.endswith("." + allowed_host):
            return True
    suffixes: Set[str] = set(_DEFAULT_OUTBOUND_IMAGE_HOST_SUFFIXES)
    extra = getattr(settings, "SECURITY_ALLOWED_OUTBOUND_IMAGE_HOSTS", "") or ""
    for part in extra.split(","):
        part = part.strip().lower().lstrip(".")
        if part:
            suffixes.add(part)
    for suffix in suffixes:
        if host == suffix or host.endswith("." + suffix):
            return True
    return False


def is_safe_outbound_image_url(url: str, settings: "Settings") -> bool:
    """SSRF-guard для серверного скачивания картинок провайдера."""
    if not url or not isinstance(url, str):
        return False
    url = url.strip()
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        return False
    if parsed.username or parsed.password:
        return False

    our_hosts = {h.split(":")[0] for h in _public_url_hosts(settings)}
    is_our_storage = host.lower() in our_hosts
    if is_our_storage:
        if parsed.scheme not in ("http", "https"):
            return False
    elif parsed.scheme != "https":
        return False

    try:
        ip = ipaddress.ip_address(host)
        if _is_private_ip(ip) and not is_our_storage:
            return False
        if _is_private_ip(ip) and is_our_storage:
            return True
    except ValueError:
        pass

    if not _outbound_host_allowed(host, settings):
        return False
    if not is_our_storage and _hostname_resolves_to_private(host):
        return False
    return True


def assert_safe_outbound_image_url(url: str, settings: "Settings") -> None:
    if not is_safe_outbound_image_url(url, settings):
        raise ValueError("Outbound image URL blocked by SSRF policy")
