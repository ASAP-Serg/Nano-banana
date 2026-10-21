"""Скачивание результата генерации и сохранение в MinIO."""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional, TYPE_CHECKING
from urllib.parse import urlparse

import urllib3
from urllib3.exceptions import HTTPError, MaxRetryError

from nano_banana.security import generate_storage_object_name, resolve_public_ip

if TYPE_CHECKING:
    from nano_banana.storage.s3 import MinioService

logger = logging.getLogger(__name__)

DOWNLOAD_CONNECT_TIMEOUT = 30
DOWNLOAD_READ_TIMEOUT = 120
DOWNLOAD_RETRIES = 5
MIN_IMAGE_BYTES = 512
MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024


def _read_stream(resp: urllib3.HTTPResponse) -> bytes:
    chunks: list[bytes] = []
    total = 0
    try:
        while True:
            chunk = resp.read(262144)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_DOWNLOAD_BYTES:
                raise ValueError("image download exceeded size limit")
            chunks.append(chunk)
    finally:
        resp.release_conn()
        resp.close()
    return b"".join(chunks)


def _pinned_request(url: str, *, read_timeout: int) -> urllib3.HTTPResponse:
    """
    GET с DNS-pin: резолвим IP один раз, коннектимся к нему, Host/SNI = исходный hostname.
    Закрывает окно DNS rebinding между проверкой SSRF и фактическим TCP.
    """
    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("missing hostname")
    if parsed.username or parsed.password:
        raise ValueError("credentials in URL blocked")
    ip = resolve_public_ip(hostname)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    headers = {
        "Host": hostname,
        "User-Agent": "NanoBanana/1.0",
        "Accept": "image/*,*/*",
    }
    timeout = urllib3.Timeout(connect=DOWNLOAD_CONNECT_TIMEOUT, read=read_timeout)
    if parsed.scheme == "https":
        pool = urllib3.HTTPSConnectionPool(
            host=ip,
            port=port,
            assert_hostname=hostname,
            server_hostname=hostname,
            cert_reqs="CERT_REQUIRED",
            retries=False,
            timeout=timeout,
        )
    elif parsed.scheme == "http":
        pool = urllib3.HTTPConnectionPool(
            host=ip,
            port=port,
            retries=False,
            timeout=timeout,
        )
    else:
        raise ValueError("unsupported scheme")
    return pool.request(
        "GET",
        path,
        headers=headers,
        redirect=False,
        preload_content=False,
    )


def download_image_from_url(
    image_url: str,
    *,
    read_timeout: int = DOWNLOAD_READ_TIMEOUT,
    retries: int = DOWNLOAD_RETRIES,
) -> Optional[bytes]:
    """Скачивает изображение по URL с повторами и DNS-pin."""
    from nano_banana.config import settings
    from nano_banana.security import assert_safe_outbound_image_url

    try:
        assert_safe_outbound_image_url(image_url, settings)
    except ValueError as blocked:
        logger.error("[RESULT] SSRF block: %s (%s)", blocked, image_url[:120])
        return None

    last_err: Optional[str] = None
    current_url = image_url
    for attempt in range(1, retries + 1):
        try:
            logger.info(
                "[RESULT] Скачивание %s/%s (pinned): %s...",
                attempt,
                retries,
                current_url[:120],
            )
            resp = _pinned_request(current_url, read_timeout=read_timeout)
            status = int(resp.status)
            if status in (301, 302, 303, 307, 308):
                loc = resp.headers.get("Location") or ""
                resp.release_conn()
                resp.close()
                try:
                    assert_safe_outbound_image_url(loc, settings)
                except ValueError:
                    last_err = "redirect blocked by SSRF policy"
                    continue
                current_url = loc
                last_err = "following safe redirect"
                continue
            if status != 200:
                last_err = f"HTTP {status}"
                resp.release_conn()
                resp.close()
                continue
            data = _read_stream(resp)
            if len(data) >= MIN_IMAGE_BYTES:
                logger.info("[RESULT] Скачано %s байт (pinned)", len(data))
                return data
            last_err = f"слишком маленький ответ ({len(data)} байт)"
        except ValueError as exc:
            last_err = str(exc)
            logger.warning("[RESULT] Ошибка скачивания: %s", exc)
        except (HTTPError, MaxRetryError, OSError) as exc:
            last_err = str(exc)
            logger.warning("[RESULT] Ошибка скачивания: %s", exc)
        if attempt < retries:
            time.sleep(min(2 * attempt, 8))
    logger.error("[RESULT] Не удалось скачать изображение: %s", last_err)
    return None


def persist_generation_result(minio: "MinioService", result: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """
    Сохраняет результат провайдера (bytes или URL) в MinIO.
    Возвращает {'url', 'path'} или None.
    """
    payload: Optional[bytes] = None
    image_data = result.get("image_data")
    if isinstance(image_data, (bytes, bytearray)) and len(image_data) >= MIN_IMAGE_BYTES:
        payload = bytes(image_data)
    else:
        image_url = result.get("image_url")
        if isinstance(image_url, str) and image_url.strip():
            payload = download_image_from_url(image_url.strip())
    if not payload:
        return None

    filename = generate_storage_object_name("results", "jpg")
    return minio.upload_image(payload, filename, "image/jpeg")
