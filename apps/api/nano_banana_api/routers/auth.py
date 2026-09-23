"""Роутер аутентификации."""
from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy import or_

from nano_banana.auth import auth_service
from nano_banana.config import settings
from nano_banana.db.models import User
from nano_banana.db.session import db_service
from nano_banana.rate_limit import check_rate_limit, client_ip_from_request
from nano_banana.schemas import UserCreateRequest, UserLoginRequest, UserResponse
from nano_banana.security import constant_time_secret_equal
from nano_banana.tokens import Token, TokenPayload

router = APIRouter(prefix="/auth", tags=["auth"])

COOKIE_NAME = "nb_access"
COOKIE_PATH = "/api"


def _cookie_secure() -> bool:
    return (settings.API_URL or "").lower().startswith("https://")


def _set_access_cookie(response: Response, token: str) -> None:
    max_age = int(settings.ACCESS_TOKEN_EXPIRE_MINUTES) * 60
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=max_age,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        path=COOKIE_PATH,
    )


def _clear_access_cookie(response: Response) -> None:
    # Clear both paths: legacy "/" and scoped "/api"
    for path in (COOKIE_PATH, "/"):
        response.delete_cookie(key=COOKIE_NAME, path=path, samesite="lax", secure=_cookie_secure())


def _bootstrap_secret_ok(header_secret: Optional[str]) -> bool:
    return constant_time_secret_equal(settings.ADMIN_BOOTSTRAP_SECRET, header_secret)


@router.post("/register", response_model=Token)
async def register(
    user_data: UserCreateRequest,
    request: Request,
    response: Response,
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

    check_rate_limit(
        "register",
        client_ip_from_request(request),
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
        access = await auth_service.create_access_token(new_user)
        _set_access_cookie(response, access)
        # Не отдаём JWT в JSON — только httpOnly cookie (XSS не сможет вытащить токен из ответа).
        return Token(access_token="", refresh_token="", token_type="cookie")


@router.post("/login", response_model=Token)
async def login(user_data: UserLoginRequest, request: Request, response: Response):
    ip = client_ip_from_request(request)
    ident = user_data.username_or_email.strip().lower()
    check_rate_limit(
        "login-ip",
        ip,
        settings.SECURITY_LOGIN_MAX_ATTEMPTS * 3,
        settings.SECURITY_LOGIN_WINDOW_SECONDS,
        "Слишком много попыток входа с этого адреса. Попробуйте позже.",
    )
    check_rate_limit(
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
        access = await auth_service.create_access_token(user)
        _set_access_cookie(response, access)
        return Token(access_token="", refresh_token="", token_type="cookie")


@router.post("/logout")
async def logout(response: Response):
    _clear_access_cookie(response)
    return {"ok": True}


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
