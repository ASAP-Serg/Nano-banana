"""Загрузка референсов в S3 на стороне API (до постановки job в очередь)."""
from __future__ import annotations

import base64
import io
import logging
import re
from typing import List, Optional, Tuple
from urllib.parse import urlparse

from PIL import Image as PILImage

from nano_banana.config import settings
from nano_banana.db.models import Generation
from nano_banana.db.session import db_service
from nano_banana.schemas import MAX_REFERENCE_IMAGES
from nano_banana.security import generate_storage_object_name
from nano_banana.storage.s3 import MinioService

logger = logging.getLogger(__name__)

MAX_DIMENSION_VALIDATION = 8192
MAX_REF_SIZE = 20 * 1024 * 1024
MAX_REF_DATA_URL_CHARS = int(MAX_REF_SIZE * 4 / 3) + 128
ALLOWED_REF_MIMES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}
_REF_PROXY_RE = re.compile(r"^/api/v1/images/(\d+)/reference/(\d+)/?$")
_FILE_PROXY_RE = re.compile(r"^/api/v1/images/(\d+)/file/?$")


def _parse_owned_media_ref(value: str) -> Optional[Tuple[str, int, Optional[int]]]:
    text = (value or "").strip()
    if text.startswith(("http://", "https://")):
        parsed = urlparse(text)
        api_host = urlparse((settings.API_URL or "").strip()).netloc.lower()
        if not parsed.netloc or parsed.netloc.lower() != api_host:
            return None
        text = parsed.path or ""
    match = _REF_PROXY_RE.match(text)
    if match:
        return ("ref", int(match.group(1)), int(match.group(2)))
    match = _FILE_PROXY_RE.match(text)
    if match:
        return ("file", int(match.group(1)), None)
    return None


def _copy_owned_object(
    minio: MinioService,
    user_id: int,
    kind: str,
    generation_id: int,
    index: Optional[int],
    *,
    allow_any_owner: bool = False,
) -> str:
    with db_service.get_session() as session:
        query = session.query(Generation).filter(Generation.id == generation_id)
        if not allow_any_owner:
            query = query.filter(Generation.user_id == user_id)
        gen = query.first()
        if not gen:
            raise ValueError("Референс недоступен")
        if kind == "ref":
            stored = (gen.generation_metadata or {}).get("reference_image_urls") or []
            if index is None or index < 0 or index >= len(stored) or not stored[index]:
                raise ValueError("Референс недоступен")
            source = stored[index]
        else:
            source = getattr(gen, "result_path", None) or gen.result_url
            if not source:
                raise ValueError("Референс недоступен")
    data, content_type = minio.get_object_bytes(source)
    ext = "jpg"
    if "png" in content_type:
        ext = "png"
    elif "webp" in content_type:
        ext = "webp"
    filename = generate_storage_object_name("references", ext)
    upload = minio.upload_image(data, filename, content_type)
    return upload["path"]


def store_reference_images(
    minio: MinioService,
    reference_images: List[str],
    user_id: int,
    *,
    allow_any_owner: bool = False,
) -> List[str]:
    urls: List[str] = []
    refs = [item for item in (reference_images or []) if item]
    if len(refs) > MAX_REFERENCE_IMAGES:
        raise ValueError(f"Максимум {MAX_REFERENCE_IMAGES} референса")
    for idx, ref_img_data in enumerate(refs):
        if not isinstance(ref_img_data, str):
            raise ValueError(f"Референс {idx + 1}: неподдерживаемый формат")
        owned = _parse_owned_media_ref(ref_img_data)
        if owned:
            kind, generation_id, index = owned
            urls.append(
                _copy_owned_object(
                    minio,
                    user_id,
                    kind,
                    generation_id,
                    index,
                    allow_any_owner=allow_any_owner,
                )
            )
            continue
        if ref_img_data.startswith("data:image"):
            if len(ref_img_data) > MAX_REF_DATA_URL_CHARS:
                raise ValueError(
                    f"Референс {idx + 1} слишком большой. Максимум 20MB"
                )
            header, _, base64_data = ref_img_data.partition(",")
            if not base64_data:
                raise ValueError(f"Референс {idx + 1} не является валидным изображением")
            mime_type = header.split(";")[0].split(":")[1] if ":" in header else "image/jpeg"
            mime_type = mime_type.strip().lower()
            if mime_type not in ALLOWED_REF_MIMES:
                raise ValueError(f"Референс {idx + 1}: допустимы JPEG, PNG или WebP")
            image_bytes = base64.b64decode(base64_data, validate=False)
            if len(image_bytes) > MAX_REF_SIZE:
                raise ValueError(
                    f"Референс {idx + 1} слишком большой "
                    f"({len(image_bytes) / 1024 / 1024:.1f}MB). Максимум 20MB"
                )
            ext = "jpg"
            if "png" in mime_type:
                ext = "png"
            elif "webp" in mime_type:
                ext = "webp"
            try:
                img = PILImage.open(io.BytesIO(image_bytes))
                img.verify()
                img = PILImage.open(io.BytesIO(image_bytes))
                if img.width > MAX_DIMENSION_VALIDATION or img.height > MAX_DIMENSION_VALIDATION:
                    raise ValueError(
                        f"Референс {idx + 1} слишком большой ({img.width}x{img.height}). "
                        f"Максимальный размер: {MAX_DIMENSION_VALIDATION}x{MAX_DIMENSION_VALIDATION}"
                    )
            except ValueError:
                raise
            except Exception as img_error:
                raise ValueError(f"Референс {idx + 1} не является валидным изображением") from img_error
            filename = generate_storage_object_name("references", ext)
            upload = minio.upload_image(image_bytes, filename, mime_type)
            urls.append(upload["path"])
            continue
        raise ValueError(
            f"Референс {idx + 1}: неподдерживаемый формат (нужен файл или своё изображение из галереи)"
        )
    return urls


def materialize_reference_images(
    minio: MinioService,
    reference_images: List[str],
    allowed_sources: Optional[List[str]] = None,
) -> List[str]:
    """Пути MinIO этой генерации → data URL. Чужие object key не читаем."""
    allowed: set[str] = set()
    for src in allowed_sources or []:
        if not isinstance(src, str):
            continue
        path = minio.extract_object_path(src)
        if path:
            allowed.add(path)
    out: List[str] = []
    for ref in reference_images or []:
        if not isinstance(ref, str) or not ref.strip():
            continue
        text = ref.strip()
        if text.startswith("data:image"):
            out.append(text)
            continue
        path = minio.extract_object_path(text)
        if not path or path not in allowed:
            raise ValueError("Референс недоступен")
        data, content_type = minio.get_object_bytes(path)
        encoded = base64.b64encode(data).decode("ascii")
        out.append(f"data:{content_type};base64,{encoded}")
    return out
