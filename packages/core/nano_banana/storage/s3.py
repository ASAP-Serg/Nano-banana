"""
S3-совместимое хранилище (MinIO локально, Object Storage в проде).
Private bucket + presigned GET (Host = MINIO_PUBLIC_URL).
"""
from __future__ import annotations

import io
import logging
from datetime import timedelta
from typing import Dict, Optional
from urllib.parse import urlparse

from minio import Minio
from minio.error import S3Error

from nano_banana.config import settings

logger = logging.getLogger(__name__)


class MinioService:
    def __init__(self):
        self.client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
        self.bucket = settings.MINIO_BUCKET
        self.public_url = settings.MINIO_PUBLIC_URL
        self.presign_expires = max(60, int(settings.MINIO_PRESIGN_EXPIRES_SECONDS))
        self._presign_client = self._build_presign_client()
        self._ensure_bucket_exists()

    def _build_presign_client(self) -> Minio:
        public = urlparse(self.public_url.rstrip("/"))
        if public.netloc and public.netloc != settings.MINIO_ENDPOINT:
            return Minio(
                public.netloc,
                access_key=settings.MINIO_ACCESS_KEY,
                secret_key=settings.MINIO_SECRET_KEY,
                secure=(public.scheme == "https"),
            )
        return self.client

    def _ensure_bucket_exists(self):
        try:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
                logger.info("[S3] bucket created %s", self.bucket)
            if settings.S3_PUBLIC_READ:
                logger.warning("[S3] S3_PUBLIC_READ=true — bucket remains publicly readable")
                return
            try:
                self.client.delete_bucket_policy(self.bucket)
                logger.info("[S3] public bucket policy removed for %s", self.bucket)
            except Exception:
                pass
        except S3Error as exc:
            logger.error("[S3] bucket init failed: %s", exc)
            raise

    def extract_object_path(self, url_or_path: Optional[str]) -> Optional[str]:
        if not url_or_path or not isinstance(url_or_path, str):
            return None
        value = url_or_path.strip()
        if value.startswith("images/"):
            return value.split("?", 1)[0]
        marker = f"/{self.bucket}/"
        if marker in value:
            path = value.split(marker, 1)[1].split("?", 1)[0]
            return path if path.startswith("images/") else None
        return None

    def upload_image(self, image_data: bytes, filename: str, content_type: str = "image/jpeg") -> Dict[str, str]:
        try:
            if not filename.startswith("images/"):
                filename = f"images/{filename}"
            logger.info("[S3] upload %s (%s bytes)", filename, len(image_data))
            self.client.put_object(
                self.bucket,
                filename,
                io.BytesIO(image_data),
                length=len(image_data),
                content_type=content_type,
            )
            if settings.S3_PUBLIC_READ:
                base_url = self.public_url.rstrip("/")
                return {"url": f"{base_url}/{self.bucket}/{filename}", "path": filename}
            return {"url": self.get_image_url(filename), "path": filename}
        except S3Error as exc:
            logger.error("[S3] upload failed: %s", exc, exc_info=True)
            raise ValueError(f"S3 upload error: {exc}") from exc

    def get_image_url(self, filename: str, expires: Optional[int] = None) -> str:
        try:
            ttl = expires if expires is not None else self.presign_expires
            return self._presign_client.presigned_get_object(
                self.bucket,
                filename,
                expires=timedelta(seconds=ttl),
            )
        except S3Error as exc:
            raise FileNotFoundError(f"Image {filename} not found") from exc

    def refresh_access_url(self, url_or_path: Optional[str]) -> Optional[str]:
        if settings.S3_PUBLIC_READ:
            return url_or_path
        path = self.extract_object_path(url_or_path)
        if not path:
            return url_or_path
        try:
            return self.get_image_url(path)
        except Exception as exc:
            logger.warning("[S3] refresh URL failed for %s: %s", path, exc)
            return url_or_path

    def delete_image(self, filename: str) -> bool:
        try:
            self.client.remove_object(self.bucket, filename)
            return True
        except S3Error as exc:
            logger.error("[S3] delete failed: %s", exc)
            return False

    def ping(self) -> bool:
        return bool(self.client.bucket_exists(self.bucket))


ObjectStorage = MinioService
