"""Скачивание результата генерации и сохранение в MinIO."""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, Optional, TYPE_CHECKING
from urllib.parse import urlparse

import requests
import urllib3
from urllib3.exceptions import HTTPError, MaxRetryError

from nano_banana.security import generate_storage_object_name, resolve_public_ip

if TYPE_CHECKING:
    from nano_banana.storage.s3 import MinioService

logger = logging.getLogger(__name__)

DOWNLOAD_CONNECT_TIMEOUT = 20
DOWNLOAD_READ_TIMEOUT = 90
DOWNLOAD_RETRIES = 3
DOWNLOAD_CHUNK_BYTES = 16 * 1024
DOWNLOAD_PARALLEL_PARTS = 8
DOWNLOAD_TOTAL_DEADLINE_SECONDS = 600
MIN_IMAGE_BYTES = 512
MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024

ProgressCb = Optional[Callable[[int, Optional[int]], None]]


def _headers() -> Dict[str, str]:
    return {
        "User-Agent": "NanoBanana/1.0",
        "Accept": "image/*,*/*",
    }


def _is_cloudflare_cdn_host(hostname: Optional[str]) -> bool:
    host = (hostname or "").lower()
    return host.endswith("rendergrid.io") or host.endswith("moonez.ai")


def _read_stream(resp: urllib3.HTTPResponse, *, on_progress: ProgressCb = None) -> bytes:
    chunks: list[bytes] = []
    total = 0
    try:
        while True:
            chunk = resp.read(DOWNLOAD_CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_DOWNLOAD_BYTES:
                raise ValueError("image download exceeded size limit")
            chunks.append(chunk)
            if on_progress:
                on_progress(total, None)
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
    headers = {**_headers(), "Host": hostname}
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


def _hostname_request(url: str, *, read_timeout: int) -> urllib3.HTTPResponse:
    """Обычный HTTPS к hostname (SNI). На Cloudflare IP-pin часто даёт Read timeout с RU VPS."""
    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("missing hostname")
    if parsed.username or parsed.password:
        raise ValueError("credentials in URL blocked")
    resolve_public_ip(hostname)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    timeout = urllib3.Timeout(connect=DOWNLOAD_CONNECT_TIMEOUT, read=read_timeout)
    if parsed.scheme == "https":
        pool = urllib3.HTTPSConnectionPool(
            host=hostname,
            port=port,
            cert_reqs="CERT_REQUIRED",
            retries=False,
            timeout=timeout,
        )
    elif parsed.scheme == "http":
        pool = urllib3.HTTPConnectionPool(
            host=hostname,
            port=port,
            retries=False,
            timeout=timeout,
        )
    else:
        raise ValueError("unsupported scheme")
    return pool.request(
        "GET",
        path,
        headers=_headers(),
        redirect=False,
        preload_content=False,
    )


def _download_range(url: str, start: int, end: int) -> tuple[int, bytes]:
    headers = {**_headers(), "Range": f"bytes={start}-{end}"}
    resp = requests.get(
        url,
        headers=headers,
        timeout=(DOWNLOAD_CONNECT_TIMEOUT, DOWNLOAD_READ_TIMEOUT),
        stream=True,
    )
    try:
        if resp.status_code not in (200, 206):
            raise ValueError(f"HTTP {resp.status_code} for range {start}-{end}")
        chunks: list[bytes] = []
        total = 0
        expected = end - start + 1
        for chunk in resp.iter_content(chunk_size=DOWNLOAD_CHUNK_BYTES):
            if not chunk:
                continue
            total += len(chunk)
            if total > expected + 1024:
                raise ValueError("range response larger than requested")
            chunks.append(chunk)
        data = b"".join(chunks)
        if len(data) < expected and resp.status_code == 206:
            raise ValueError(f"short range {start}-{end}: got {len(data)} want {expected}")
        return start, data
    finally:
        resp.close()


def _parallel_range_download(url: str, *, on_progress: ProgressCb = None) -> Optional[bytes]:
    """Параллельные Range-GET — с медленного RU→CF пути заметно быстрее одного потока."""
    head = requests.get(
        url,
        headers={**_headers(), "Range": "bytes=0-0"},
        timeout=(DOWNLOAD_CONNECT_TIMEOUT, DOWNLOAD_READ_TIMEOUT),
        stream=True,
    )
    try:
        if head.status_code not in (200, 206):
            raise ValueError(f"HTTP {head.status_code} on size probe")
        content_range = head.headers.get("Content-Range") or ""
        total_size: Optional[int] = None
        if "/" in content_range:
            try:
                total_size = int(content_range.rsplit("/", 1)[-1])
            except ValueError:
                total_size = None
        if total_size is None:
            cl = head.headers.get("Content-Length")
            if cl and head.status_code == 200:
                total_size = int(cl)
        if not total_size or total_size < MIN_IMAGE_BYTES:
            raise ValueError("could not determine image size for ranged download")
        if total_size > MAX_DOWNLOAD_BYTES:
            raise ValueError("image download exceeded size limit")
    finally:
        head.close()

    parts = min(DOWNLOAD_PARALLEL_PARTS, max(1, total_size // (64 * 1024)))
    part_size = (total_size + parts - 1) // parts
    ranges = []
    for i in range(parts):
        start = i * part_size
        end = min(total_size - 1, start + part_size - 1)
        if start <= end:
            ranges.append((start, end))

    logger.info(
        "[RESULT] parallel range download size=%s parts=%s url=%s...",
        total_size,
        len(ranges),
        url[:120],
    )
    assembled = bytearray(total_size)
    done_bytes = 0
    started = time.time()
    with ThreadPoolExecutor(max_workers=len(ranges)) as pool:
        futures = [pool.submit(_download_range, url, start, end) for start, end in ranges]
        for fut in as_completed(futures):
            start, data = fut.result()
            assembled[start : start + len(data)] = data
            done_bytes += len(data)
            if on_progress:
                on_progress(done_bytes, total_size)
            logger.info(
                "[RESULT] range progress %s/%s (%.0f%%) elapsed=%.1fs",
                done_bytes,
                total_size,
                100.0 * done_bytes / total_size,
                time.time() - started,
            )
    return bytes(assembled)


def _requests_stream_download(url: str, *, on_progress: ProgressCb = None) -> bytes:
    resp = requests.get(
        url,
        headers=_headers(),
        timeout=(DOWNLOAD_CONNECT_TIMEOUT, DOWNLOAD_READ_TIMEOUT),
        stream=True,
    )
    try:
        status = int(resp.status_code)
        if status in (301, 302, 303, 307, 308):
            loc = resp.headers.get("Location") or ""
            raise RuntimeError(f"redirect:{loc}")
        if status != 200:
            raise ValueError(f"HTTP {status}")
        chunks: list[bytes] = []
        total = 0
        last_log = 0
        for chunk in resp.iter_content(chunk_size=DOWNLOAD_CHUNK_BYTES):
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_DOWNLOAD_BYTES:
                raise ValueError("image download exceeded size limit")
            chunks.append(chunk)
            if on_progress:
                on_progress(total, None)
            if total - last_log >= 64 * 1024:
                logger.info("[RESULT] streamed %s bytes...", total)
                last_log = total
        data = b"".join(chunks)
        if len(data) < MIN_IMAGE_BYTES:
            raise ValueError(f"слишком маленький ответ ({len(data)} байт)")
        return data
    finally:
        resp.close()


def download_image_from_url(
    image_url: str,
    *,
    read_timeout: int = DOWNLOAD_READ_TIMEOUT,
    retries: int = DOWNLOAD_RETRIES,
    on_progress: ProgressCb = None,
) -> Optional[bytes]:
    """Скачивает изображение по URL. Для CDN — параллельные Range, иначе stream/SNI."""
    from nano_banana.config import settings
    from nano_banana.security import assert_safe_outbound_image_url

    try:
        assert_safe_outbound_image_url(image_url, settings)
    except ValueError as blocked:
        logger.error("[RESULT] SSRF block: %s (%s)", blocked, image_url[:120])
        return None

    last_err: Optional[str] = None
    current_url = image_url
    host = urlparse(current_url).hostname
    deadline = time.time() + DOWNLOAD_TOTAL_DEADLINE_SECONDS

    for attempt in range(1, retries + 1):
        if time.time() > deadline:
            last_err = "download deadline exceeded"
            break
        try:
            if _is_cloudflare_cdn_host(host):
                data = _parallel_range_download(current_url, on_progress=on_progress)
                if data and len(data) >= MIN_IMAGE_BYTES:
                    logger.info("[RESULT] Скачано %s байт (parallel-range)", len(data))
                    return data
                last_err = "empty parallel-range body"
            else:
                data = _requests_stream_download(current_url, on_progress=on_progress)
                logger.info("[RESULT] Скачано %s байт (requests-stream)", len(data))
                return data
        except RuntimeError as exc:
            msg = str(exc)
            if msg.startswith("redirect:"):
                loc = msg.split(":", 1)[1]
                try:
                    assert_safe_outbound_image_url(loc, settings)
                except ValueError:
                    last_err = "redirect blocked by SSRF policy"
                    break
                current_url = loc
                host = urlparse(current_url).hostname
                last_err = "following safe redirect"
                continue
            last_err = msg
            logger.warning("[RESULT] Ошибка скачивания: %s", exc)
        except ValueError as exc:
            last_err = str(exc)
            logger.warning("[RESULT] Ошибка скачивания: %s", exc)
            # 4xx — бессмысленно ретраить тем же URL
            if str(exc).startswith("HTTP 4"):
                break
        except (HTTPError, MaxRetryError, OSError, requests.RequestException) as exc:
            last_err = str(exc)
            logger.warning("[RESULT] Ошибка скачивания: %s", exc)

        # Fallback: одиночный SNI stream (без pinned — на CF с RU это только удваивает таймауты)
        if time.time() > deadline:
            break
        try:
            logger.info(
                "[RESULT] fallback SNI %s/%s: %s...",
                attempt,
                retries,
                current_url[:120],
            )
            resp = _hostname_request(current_url, read_timeout=read_timeout)
            status = int(resp.status)
            if status in (301, 302, 303, 307, 308):
                loc = resp.headers.get("Location") or ""
                resp.release_conn()
                resp.close()
                try:
                    assert_safe_outbound_image_url(loc, settings)
                except ValueError:
                    last_err = "redirect blocked by SSRF policy"
                    break
                current_url = loc
                host = urlparse(current_url).hostname
                continue
            if status != 200:
                last_err = f"HTTP {status} (sni)"
                resp.release_conn()
                resp.close()
                if 400 <= status < 500:
                    break
            else:
                data = _read_stream(resp, on_progress=on_progress)
                if len(data) >= MIN_IMAGE_BYTES:
                    logger.info("[RESULT] Скачано %s байт (sni)", len(data))
                    return data
                last_err = f"слишком маленький ответ ({len(data)} байт)"
        except ValueError as exc:
            last_err = str(exc)
            logger.warning("[RESULT] Ошибка скачивания (sni): %s", exc)
        except (HTTPError, MaxRetryError, OSError) as exc:
            last_err = str(exc)
            logger.warning("[RESULT] Ошибка скачивания (sni): %s", exc)

        if attempt < retries:
            time.sleep(min(2 * attempt, 8))

    logger.error("[RESULT] Не удалось скачать изображение: %s", last_err)
    return None


def persist_generation_result(
    minio: "MinioService",
    result: Dict[str, Any],
    *,
    on_progress: ProgressCb = None,
) -> Optional[Dict[str, str]]:
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
            payload = download_image_from_url(image_url.strip(), on_progress=on_progress)
    if not payload:
        return None

    filename = generate_storage_object_name("results", "jpg")
    return minio.upload_image(payload, filename, "image/jpeg")
