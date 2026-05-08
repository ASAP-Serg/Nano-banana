"""
Сервис шифрования чувствительных данных (API ключей).
"""

import base64
import hashlib
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


class CryptoService:
    """Шифрование/дешифрование на базе Fernet с ключом от SECRET_KEY."""

    @staticmethod
    def _get_fernet() -> Fernet:
        digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
        fernet_key = base64.urlsafe_b64encode(digest)
        return Fernet(fernet_key)

    @classmethod
    def encrypt(cls, value: str) -> str:
        if not value:
            return ""
        return cls._get_fernet().encrypt(value.encode("utf-8")).decode("utf-8")

    @classmethod
    def decrypt(cls, token: str) -> Optional[str]:
        if not token:
            return None
        try:
            return cls._get_fernet().decrypt(token.encode("utf-8")).decode("utf-8")
        except (InvalidToken, ValueError, TypeError):
            return None

