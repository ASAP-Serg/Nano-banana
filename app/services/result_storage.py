"""Скачивание результата генерации и сохранение в MinIO."""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional, TYPE_CHECKING

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.security_helpers import generate_storage_object_name

if TYPE_CHECKING:
    from app.services.MinioService import MinioService

logger = logging.getLogger(__name__)

DOWNLOAD_CONNECT_TIMEOUT = 30
DOWNLOAD_READ_TIMEOUT = 120
DOWNLOAD_RETRIES = 5
MIN_IMAGE_BYTES = 512


def _download_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": "NanoBanana/1.0", "Accept": "image/*,*/*"})
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        backoff_factor=0.5,
        status_forcelist=(502, 503, 504),
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=4)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _read_response_bytes(resp: requests.Response, *, stream: bool) -> bytes:
    if stream:
        chunks: list[bytes] = []
        for chunk in resp.iter_content(chunk_size=262144):
            if chunk:
                chunks.append(chunk)
        return b"".join(chunks)
    return resp.content


def download_image_from_url(
    image_url: str,
    *,
    read_timeout: int = DOWNLOAD_READ_TIMEOUT,
    retries: int = DOWNLOAD_RETRIES,
) -> Optional[bytes]:
    """Скачивает изображение по URL с повторами (stream + fallback без stream)."""
    last_err: Optional[str] = None
    session = _download_session()
    for attempt in range(1, retries + 1):
        for stream in (True, False):
            mode = "stream" if stream else "buffer"
            try:
                logger.info(
                    "[RESULT] Скачивание %s/%s (%s): %s...",
                    attempt,
                    retries,
                    mode,
                    image_url[:120],
                )
                resp = session.get(
                    image_url,
                    timeout=(DOWNLOAD_CONNECT_TIMEOUT, read_timeout),
                    stream=stream,
                )
                if resp.status_code != 200:
                    last_err = f"HTTP {resp.status_code}"
                    resp.close()
                    continue
                data = _read_response_bytes(resp, stream=stream)
                resp.close()
                if len(data) >= MIN_IMAGE_BYTES:
                    logger.info("[RESULT] Скачано %s байт (%s)", len(data), mode)
                    return data
                last_err = f"слишком маленький ответ ({len(data)} байт)"
            except Exception as exc:
                last_err = str(exc)
                logger.warning("[RESULT] Ошибка скачивания (%s): %s", mode, exc)
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
