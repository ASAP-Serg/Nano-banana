"""Ключи пользователя (Moonez / Replicate / OpenRouter) из зашифрованного поля в БД."""
from __future__ import annotations

import json
from typing import Dict, Optional

from nano_banana.crypto import CryptoService
from nano_banana.db.models import User
from nano_banana.db.session import db_service
from nano_banana.providers.detect import infer_image_api_provider
from nano_banana.providers.models import select_api_key_for_model

EMPTY_KEYS = {"replicate": "", "bananalab": "", "openrouter": ""}


def parse_stored_keys(encrypted: Optional[str]) -> Dict[str, str]:
    decrypted = CryptoService.decrypt(encrypted) if encrypted else None
    if not decrypted:
        return dict(EMPTY_KEYS)
    try:
        parsed = json.loads(decrypted)
        if isinstance(parsed, dict):
            return {
                "replicate": str(parsed.get("replicate") or "").strip(),
                "bananalab": str(parsed.get("bananalab") or "").strip(),
                "openrouter": str(parsed.get("openrouter") or "").strip(),
            }
    except Exception:
        pass
    key = str(decrypted).strip()
    if not key:
        return dict(EMPTY_KEYS)
    keys = dict(EMPTY_KEYS)
    keys[infer_image_api_provider(key)] = key
    return keys


def load_user_api_keys(user_id: int) -> Dict[str, str]:
    with db_service.get_session() as session:
        db_user = session.query(User).filter(User.id == user_id).first()
        encrypted = db_user.replicate_api_key if db_user else None
    return parse_stored_keys(encrypted)


def dump_user_api_keys(keys: dict) -> Optional[str]:
    replicate_key = str(keys.get("replicate") or "").strip()
    bananalab_key = str(keys.get("bananalab") or "").strip()
    openrouter_key = str(keys.get("openrouter") or "").strip()
    if not replicate_key and not bananalab_key and not openrouter_key:
        return None
    payload = json.dumps(
        {
            "replicate": replicate_key,
            "bananalab": bananalab_key,
            "openrouter": openrouter_key,
        },
        ensure_ascii=False,
    )
    return CryptoService.encrypt(payload)


def select_key_for_model(user_id: int, model_name: Optional[str], api_key_from_request: Optional[str] = None) -> str:
    keys = load_user_api_keys(user_id)
    return select_api_key_for_model(model_name, keys, api_key_from_request)
