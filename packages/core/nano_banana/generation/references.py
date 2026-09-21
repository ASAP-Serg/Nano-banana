"""Загрузка референсов в S3 на стороне API (до постановки job в очередь)."""
from __future__ import annotations

import base64
import io
import logging
from typing import List

from PIL import Image as PILImage

from nano_banana.config import settings
from nano_banana.security import generate_storage_object_name, is_allowed_reference_url
from nano_banana.storage.s3 import MinioService

logger = logging.getLogger(__name__)

MAX_DIMENSION_VALIDATION = 8192
MAX_REF_SIZE = 20 * 1024 * 1024


def store_reference_images(minio: MinioService, reference_images: List[str]) -> List[str]:
    urls: List[str] = []
    for idx, ref_img_data in enumerate(reference_images or []):
        if not ref_img_data:
            continue
        if ref_img_data.startswith("data:image"):
            header, base64_data = ref_img_data.split(",", 1)
            mime_type = header.split(";")[0].split(":")[1] if ":" in header else "image/jpeg"
            image_bytes = base64.b64decode(base64_data)
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
                if len(image_bytes) > MAX_REF_SIZE:
                    raise ValueError(
                        f"Референс {idx + 1} слишком большой "
                        f"({len(image_bytes) / 1024 / 1024:.1f}MB). Максимум 20MB"
                    )
            except ValueError:
                raise
            except Exception as img_error:
                raise ValueError(f"Референс {idx + 1} не является валидным изображением: {img_error}") from img_error
            filename = generate_storage_object_name("references", ext)
            upload = minio.upload_image(image_bytes, filename, mime_type)
            urls.append(upload["url"])
        elif ref_img_data.startswith(("http://", "https://")):
            if not is_allowed_reference_url(ref_img_data, settings):
                raise ValueError(
                    f"Референс {idx + 1}: разрешены только ссылки на файлы вашего хранилища "
                    f"({settings.MINIO_PUBLIC_URL})"
                )
            urls.append(ref_img_data)
        else:
            raise ValueError(
                f"Референс {idx + 1}: неподдерживаемый формат (нужен data:image или URL хранилища)"
            )
    return urls
