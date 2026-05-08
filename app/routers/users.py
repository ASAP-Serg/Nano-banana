"""
Роутер для управления пользователями и API ключами
"""
import json
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from app.models.schemas import ReplicateApiKeyRequest, ReplicateApiKeyResponse, UserResponse
from app.services.DBService import db_service
from app.services.AuthService import auth_service
from app.services.CryptoService import CryptoService
from app.models.base import User
from app.models.token import TokenPayload
from app.services.image_api_provider import infer_image_api_provider
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["users"])


def _load_user_api_keys(db_user: User) -> dict:
    encrypted = db_user.replicate_api_key
    if not encrypted:
        return {"replicate": "", "bananalab": ""}
    decrypted = CryptoService.decrypt(encrypted)
    if not decrypted:
        return {"replicate": "", "bananalab": ""}
    try:
        payload = json.loads(decrypted)
        if isinstance(payload, dict):
            return {
                "replicate": str(payload.get("replicate") or "").strip(),
                "bananalab": str(payload.get("bananalab") or "").strip(),
            }
    except Exception:
        pass
    # Legacy-формат: один ключ строкой
    legacy = decrypted.strip()
    if not legacy:
        return {"replicate": "", "bananalab": ""}
    if infer_image_api_provider(legacy) == "bananalab":
        return {"replicate": "", "bananalab": legacy}
    return {"replicate": legacy, "bananalab": ""}


def _save_user_api_keys(db_user: User, keys: dict):
    replicate_key = str(keys.get("replicate") or "").strip()
    bananalab_key = str(keys.get("bananalab") or "").strip()
    if not replicate_key and not bananalab_key:
        db_user.replicate_api_key = None
        return
    payload = json.dumps({"replicate": replicate_key, "bananalab": bananalab_key}, ensure_ascii=False)
    db_user.replicate_api_key = CryptoService.encrypt(payload)


def _normalize_provider(provider: str, api_key: str) -> str:
    p = (provider or "").strip().lower()
    if p in ("replicate", "bananalab"):
        return p
    return infer_image_api_provider(api_key)

@router.put("/api-key", response_model=ReplicateApiKeyResponse)
async def set_replicate_api_key(
    request: ReplicateApiKeyRequest,
    user: Annotated[TokenPayload, Depends(auth_service.get_current_user)]
):
    """
    Сохраняет API ключ пользователя в БД в зашифрованном виде.
    """
    api_key = (request.api_key or "").strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="API ключ пустой")

    with db_service.get_session() as session:
        db_user = session.query(User).filter(User.id == user.user_id).first()
        if not db_user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        keys = _load_user_api_keys(db_user)
        provider = _normalize_provider(request.provider or "", api_key)
        keys[provider] = api_key
        _save_user_api_keys(db_user, keys)
        session.commit()

    logger.info(f"[USER] API ключ ({provider}) зашифрован и сохранен для пользователя {user.user_id}")
    return ReplicateApiKeyResponse(
        message=f"API ключ {provider} сохранен в зашифрованном виде",
        has_key=True,
        has_replicate_key=bool(keys.get("replicate")),
        has_bananalab_key=bool(keys.get("bananalab")),
        selected_provider=("bananalab" if keys.get("bananalab") else ("replicate" if keys.get("replicate") else "unknown")),
    )

@router.get("/api-key", response_model=ReplicateApiKeyResponse)
async def get_replicate_api_key_status(
    user: Annotated[TokenPayload, Depends(auth_service.get_current_user)]
):
    """
    Проверяет, сохранен ли API ключ пользователя на сервере.
    """
    with db_service.get_session() as session:
        db_user = session.query(User).filter(User.id == user.user_id).first()
        if not db_user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        keys = _load_user_api_keys(db_user)
        has_replicate_key = bool(keys.get("replicate"))
        has_bananalab_key = bool(keys.get("bananalab"))
        has_key = has_replicate_key or has_bananalab_key

    return ReplicateApiKeyResponse(
        message="Ключи сохранены на сервере (зашифрованы)" if has_key else "Ключи на сервере не сохранены",
        has_key=has_key,
        has_replicate_key=has_replicate_key,
        has_bananalab_key=has_bananalab_key,
        selected_provider=("bananalab" if has_bananalab_key else ("replicate" if has_replicate_key else "unknown")),
    )

@router.delete("/api-key")
async def delete_replicate_api_key(
    user: Annotated[TokenPayload, Depends(auth_service.get_current_user)]
):
    """
    Удаляет сохраненный API ключ пользователя из БД.
    """
    with db_service.get_session() as session:
        db_user = session.query(User).filter(User.id == user.user_id).first()
        if not db_user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        _save_user_api_keys(db_user, {"replicate": "", "bananalab": ""})
        session.commit()

    logger.info(f"[USER] Все API ключи удалены для пользователя {user.user_id}")
    return {"message": "Все API ключи удалены с сервера"}


