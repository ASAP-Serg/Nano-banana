"""
Сервис шифрования чувствительных данных (API ключей).
"""

import base64
import hashlib
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from nano_banana.config import settings


class CryptoService:
    """Шифрование API-ключей. DATA_ENCRYPTION_KEY отдельно от JWT SECRET_KEY."""

    @staticmethod
    def _material() -> bytes:
        return (settings.DATA_ENCRYPTION_KEY or settings.SECRET_KEY or "").encode("utf-8")

    @staticmethod
    def _fernet_from(material: bytes) -> Fernet:
        digest = hashlib.sha256(material).digest()
        return Fernet(base64.urlsafe_b64encode(digest))

    @classmethod
    def _get_fernet(cls) -> Fernet:
        return cls._fernet_from(cls._material())

    @classmethod
    def encrypt(cls, value: str) -> str:
        if not value:
            return ""
        return cls._get_fernet().encrypt(value.encode("utf-8")).decode("utf-8")

    @classmethod
    def decrypt(cls, token: str) -> Optional[str]:
        if not token:
            return None
        keys = []
        primary = cls._material()
        keys.append(primary)
        # Старые записи могли быть зашифрованы SECRET_KEY до введения DATA_ENCRYPTION_KEY
        legacy = settings.SECRET_KEY.encode("utf-8")
        if legacy != primary:
            keys.append(legacy)
        for material in keys:
            try:
                return cls._fernet_from(material).decrypt(token.encode("utf-8")).decode("utf-8")
            except (InvalidToken, ValueError, TypeError):
                continue
        return None

