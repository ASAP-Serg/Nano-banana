"""Ключи провайдеров пользователя."""
from typing import Annotated
import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from nano_banana.access import require_sensitive_access
from nano_banana.auth import auth_service
from nano_banana.db.models import User
from nano_banana.db.session import db_service
from nano_banana.generation.keys import dump_user_api_keys, parse_stored_keys
from nano_banana.providers.detect import infer_image_api_provider
from nano_banana.rate_limit import check_rate_limit, client_ip_from_request
from nano_banana.schemas import ReplicateApiKeyRequest, ReplicateApiKeyResponse
from nano_banana.tokens import TokenPayload

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/users", tags=["users"])
_EMPTY = {"replicate": "", "bananalab": "", "openrouter": ""}


def _selected_provider(keys: dict) -> str:
    if keys.get("bananalab"):
        return "bananalab"
    if keys.get("openrouter"):
        return "openrouter"
    if keys.get("replicate"):
        return "replicate"
    return "unknown"


def _key_response(message: str, keys: dict) -> ReplicateApiKeyResponse:
    has_replicate_key = bool(keys.get("replicate"))
    has_bananalab_key = bool(keys.get("bananalab"))
    has_openrouter_key = bool(keys.get("openrouter"))
    return ReplicateApiKeyResponse(
        message=message,
        has_key=has_replicate_key or has_bananalab_key or has_openrouter_key,
        has_replicate_key=has_replicate_key,
        has_bananalab_key=has_bananalab_key,
        has_openrouter_key=has_openrouter_key,
        selected_provider=_selected_provider(keys),
    )


@router.put("/api-key", response_model=ReplicateApiKeyResponse)
async def set_api_key(
    request: ReplicateApiKeyRequest,
    http_request: Request,
    user: Annotated[TokenPayload, Depends(auth_service.get_current_user)],
):
    check_rate_limit(
        "api-key-put",
        f"{client_ip_from_request(http_request)}:{user.user_id}",
        20,
        3600,
        "Слишком много изменений ключей. Попробуйте позже.",
    )
    api_key = (request.api_key or "").strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="API ключ пустой")
    if len(api_key) > 512:
        raise HTTPException(status_code=400, detail="API ключ слишком длинный")
    provider = (request.provider or "").strip().lower()
    if provider not in ("replicate", "bananalab", "openrouter"):
        provider = infer_image_api_provider(api_key)
    with db_service.get_session() as session:
        db_user = session.query(User).filter(User.id == user.user_id).first()
        if not db_user or not db_user.is_active:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        require_sensitive_access(db_user)
        keys = parse_stored_keys(db_user.replicate_api_key)
        keys[provider] = api_key
        db_user.replicate_api_key = dump_user_api_keys(keys)
        session.commit()
    logger.info("[USER] API ключ (%s) сохранён для пользователя %s", provider, user.user_id)
    return _key_response(f"API ключ {provider} сохранен в зашифрованном виде", keys)


@router.get("/api-key", response_model=ReplicateApiKeyResponse)
async def get_api_key_status(user: Annotated[TokenPayload, Depends(auth_service.get_current_user)]):
    with db_service.get_session() as session:
        db_user = session.query(User).filter(User.id == user.user_id).first()
        if not db_user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        keys = parse_stored_keys(db_user.replicate_api_key)
    message = "Ключи сохранены на сервере (зашифрованы)" if any(keys.values()) else "Ключи на сервере не сохранены"
    return _key_response(message, keys)


@router.delete("/api-key")
async def delete_api_key(
    http_request: Request,
    user: Annotated[TokenPayload, Depends(auth_service.get_current_user)],
):
    check_rate_limit(
        "api-key-del",
        f"{client_ip_from_request(http_request)}:{user.user_id}",
        20,
        3600,
        "Слишком много запросов. Попробуйте позже.",
    )
    with db_service.get_session() as session:
        db_user = session.query(User).filter(User.id == user.user_id).first()
        if not db_user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        db_user.replicate_api_key = None
        session.commit()
    logger.info("[USER] Все API ключи удалены для пользователя %s", user.user_id)
    return {"message": "Все API ключи удалены с сервера"}
