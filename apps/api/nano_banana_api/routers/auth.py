"""Роутер аутентификации."""
from datetime import datetime
import threading
import time
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import or_

from nano_banana.auth import auth_service
from nano_banana.config import settings
from nano_banana.db.models import User
from nano_banana.db.session import db_service
from nano_banana.schemas import UserCreateRequest, UserLoginRequest, UserResponse
from nano_banana.tokens import Token, TokenPayload

router = APIRouter(prefix="/auth", tags=["auth"])
_login_attempts = {}
_login_lock = threading.Lock()


def _rate_limit_auth(scope: str, identifier: str, max_attempts: int, window_seconds: int, detail: str):
    now = time.time()
    key = f"{scope}:{identifier}"
    with _login_lock:
        attempts = _login_attempts.get(key, [])
        attempts = [ts for ts in attempts if now - ts <= window_seconds]
        if len(attempts) >= max_attempts:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=detail)
        attempts.append(now)
        _login_attempts[key] = attempts


def _client_ip(request: Request) -> str:
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip().lower()
    client_host = request.client.host if request.client else None
    if client_host and client_host not in ("127.0.0.1", "::1"):
        return client_host.lower()
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip().lower()
    if client_host:
        return client_host.lower()
    return "unknown"


def _bootstrap_secret_ok(header_secret: Optional[str]) -> bool:
    expected = (settings.ADMIN_BOOTSTRAP_SECRET or "").strip()
    if not expected or not header_secret:
        return False
    return header_secret.strip() == expected


@router.post("/register", response_model=Token)
async def register(
    user_data: UserCreateRequest,
    request: Request,
    x_admin_bootstrap_secret: Annotated[Optional[str], Header()] = None,
):
    with db_service.get_session() as session:
        users_count = session.query(User).count()

    bootstrap_ok = _bootstrap_secret_ok(x_admin_bootstrap_secret)
    if not settings.SECURITY_ALLOW_PUBLIC_REGISTER:
        if not (bootstrap_ok and users_count == 0):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Регистрация отключена. Обратитесь к администратору.",
            )

    _rate_limit_auth(
        "register",
        _client_ip(request),
        settings.SECURITY_REGISTER_MAX_ATTEMPTS,
        settings.SECURITY_REGISTER_WINDOW_SECONDS,
        "Слишком много попыток регистрации с этого адреса. Попробуйте позже.",
    )
    with db_service.get_session() as session:
        users_count = session.query(User).count()
        existing_user = session.query(User).filter(
            or_(User.username == user_data.username, User.email == user_data.email)
        ).first()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Пользователь с таким именем или email уже существует",
            )
        make_admin = users_count == 0 and bootstrap_ok
        hashed_password = auth_service.get_password_hash(user_data.password)
        new_user = User(
            username=user_data.username,
            email=user_data.email,
            hashed_password=hashed_password,
            is_active=True,
            is_admin=make_admin,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            last_login=datetime.utcnow(),
        )
        session.add(new_user)
        session.commit()
        session.refresh(new_user)
        return Token(
            access_token=await auth_service.create_access_token(new_user),
            refresh_token=await auth_service.create_refresh_token(new_user),
            token_type="bearer",
        )


@router.post("/login", response_model=Token)
async def login(user_data: UserLoginRequest, request: Request):
    ip = _client_ip(request)
    ident = user_data.username_or_email.strip().lower()
    _rate_limit_auth(
        "login-ip",
        ip,
        settings.SECURITY_LOGIN_MAX_ATTEMPTS * 3,
        settings.SECURITY_LOGIN_WINDOW_SECONDS,
        "Слишком много попыток входа с этого адреса. Попробуйте позже.",
    )
    _rate_limit_auth(
        "login-user",
        f"{ip}:{ident}",
        settings.SECURITY_LOGIN_MAX_ATTEMPTS,
        settings.SECURITY_LOGIN_WINDOW_SECONDS,
        "Слишком много попыток входа. Попробуйте позже.",
    )
    with db_service.get_session() as session:
        user = session.query(User).filter(
            or_(
                User.username == user_data.username_or_email,
                User.email == user_data.username_or_email,
            )
        ).first()
        if not user or not auth_service.verify_password(user_data.password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Неверное имя пользователя/email или пароль",
            )
        if not user.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Аккаунт пользователя отключен")
        user.last_login = datetime.utcnow()
        session.commit()
        return Token(
            access_token=await auth_service.create_access_token(user),
            refresh_token=await auth_service.create_refresh_token(user),
            token_type="bearer",
        )


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(user: Annotated[TokenPayload, Depends(auth_service.get_current_user)]):
    with db_service.get_session() as session:
        db_user = session.query(User).filter(User.id == user.user_id).first()
        if not db_user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        return UserResponse(
            id=db_user.id,
            username=db_user.username,
            email=db_user.email,
            is_active=db_user.is_active,
            is_admin=db_user.is_admin,
            created_at=db_user.created_at,
        )
