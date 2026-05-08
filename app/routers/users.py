"""
Роутер для управления пользователями и API ключами
"""
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from app.models.schemas import ReplicateApiKeyRequest, ReplicateApiKeyResponse, UserResponse
from app.services.DBService import db_service
from app.services.AuthService import auth_service
from app.services.CryptoService import CryptoService
from app.models.base import User
from app.models.token import TokenPayload
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["users"])

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

    encrypted_key = CryptoService.encrypt(api_key)
    with db_service.get_session() as session:
        db_user = session.query(User).filter(User.id == user.user_id).first()
        if not db_user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        db_user.replicate_api_key = encrypted_key
        session.commit()

    logger.info(f"[USER] API ключ зашифрован и сохранен для пользователя {user.user_id}")
    return ReplicateApiKeyResponse(
        message="API ключ сохранен в зашифрованном виде",
        has_key=True
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
        has_key = bool(db_user.replicate_api_key)

    return ReplicateApiKeyResponse(
        message="API ключ сохранен на сервере (зашифрован)" if has_key else "API ключ на сервере не сохранен",
        has_key=has_key
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
        db_user.replicate_api_key = None
        session.commit()

    logger.info(f"[USER] API ключ удален для пользователя {user.user_id}")
    return {"message": "API ключ удален с сервера"}


