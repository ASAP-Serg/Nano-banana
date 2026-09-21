"""
S3-совместимое хранилище (MinIO локально, Object Storage в проде).
"""
from __future__ import annotations

import io
import json
import logging
from datetime import timedelta
from typing import Dict

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
        self._ensure_bucket_exists()

    def _ensure_bucket_exists(self):
        try:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
                logger.info("[S3] bucket created %s", self.bucket)
            if not settings.S3_PUBLIC_READ:
                return
            policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"AWS": ["*"]},
                        "Action": ["s3:GetObject"],
                        "Resource": [f"arn:aws:s3:::{self.bucket}/*"],
                    }
                ],
            }
            try:
                self.client.set_bucket_policy(self.bucket, json.dumps(policy))
            except S3Error as exc:
                logger.warning("[S3] bucket policy skipped: %s", exc)
        except S3Error as exc:
            logger.error("[S3] bucket init failed: %s", exc)
            raise

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
            base_url = self.public_url.rstrip("/")
            public_url = f"{base_url}/{self.bucket}/{filename}"
            return {"url": public_url, "path": filename}
        except S3Error as exc:
            logger.error("[S3] upload failed: %s", exc, exc_info=True)
            raise ValueError(f"S3 upload error: {exc}") from exc

    def get_image_url(self, filename: str, expires: int = 3600) -> str:
        try:
            return self.client.presigned_get_object(
                self.bucket,
                filename,
                expires=timedelta(seconds=expires),
            )
        except S3Error as exc:
            raise FileNotFoundError(f"Image {filename} not found") from exc

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
