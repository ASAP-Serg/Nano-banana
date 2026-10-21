"""Роутер аутентификации: пароль, TOTP, trusted device, Google OAuth."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Optional
from urllib.parse import urlencode

import pyotp
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from jose import JWTError, jwt
from sqlalchemy import or_, text
from sqlalchemy.exc import IntegrityError

from nano_banana.auth import auth_service
from nano_banana.config import settings
from nano_banana.crypto import CryptoService
from nano_banana.db.models import AdminAuditLog, Generation, User
from nano_banana.db.session import db_service
from nano_banana.google_oauth import (
    OAUTH_STATE_COOKIE,
    PENDING_2FA_COOKIE,
    build_authorize_url,
    exchange_code_for_userinfo,
    google_oauth_configured,
    new_oauth_state,
    unique_username,
    username_from_google,
)
from nano_banana.email_tokens import (
    PURPOSE_RESET,
    PURPOSE_VERIFY,
    consume_token,
    issue_token,
)
from nano_banana.mail import mail_configured, send_reset_password_email, send_verify_email
from nano_banana.rate_limit import check_rate_limit, client_ip_from_request
from nano_banana.schemas import (
    CompleteProfileRequest,
    DeleteAccountRequest,
    ForgotPasswordRequest,
    PasswordChangeRequest,
    ResendVerifyRequest,
    ResetPasswordRequest,
    TotpCompleteRequest,
    TotpConfirmRequest,
    UpdateEmailRequest,
    UsernameChangeRequest,
    UserCreateRequest,
    UserLoginRequest,
    UserResponse,
)
from nano_banana.generation.cleanup import delete_generation_assets
from nano_banana.storage.s3 import MinioService
from nano_banana.security import constant_time_secret_equal
from nano_banana.tokens import Token, TokenPayload
from nano_banana.totp_qr import otpauth_qr_data_url
from nano_banana.trusted_device import (
    COOKIE_PATH,
    TRUSTED_COOKIE,
    find_valid_trusted_device,
    issue_trusted_device,
    revoke_all_trusted_devices,
    revoke_trusted_device_by_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])

COOKIE_NAME = "nb_access"
PENDING_PROFILE_COOKIE = "nb_pending_profile"
_LOGIN_FAIL = "Неверное имя пользователя/email или пароль"
_BOOTSTRAP_LOCK_KEY = 742901001
_PENDING_2FA_MINUTES = 5
_PENDING_PROFILE_MINUTES = 15


def _cookie_secure() -> bool:
    return (settings.API_URL or "").lower().startswith("https://")


def _frontend_base() -> str:
    return (settings.API_URL or "").rstrip("/") or ""


def _set_access_cookie(response: Response, token: str) -> None:
    max_age = int(settings.ACCESS_TOKEN_EXPIRE_MINUTES) * 60
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=max_age,
        httponly=True,
        secure=_cookie_secure(),
        samesite="strict",
        path=COOKIE_PATH,
    )


def _clear_access_cookie(response: Response) -> None:
    for path in (COOKIE_PATH, "/"):
        response.delete_cookie(
            key=COOKIE_NAME,
            path=path,
            samesite="strict",
            secure=_cookie_secure(),
        )


def _set_trusted_cookie(response: Response, raw: str, max_age: int) -> None:
    response.set_cookie(
        key=TRUSTED_COOKIE,
        value=raw,
        max_age=max_age,
        httponly=True,
        secure=_cookie_secure(),
        samesite="strict",
        path=COOKIE_PATH,
    )


def _clear_trusted_cookie(response: Response) -> None:
    for path in (COOKIE_PATH, "/"):
        response.delete_cookie(
            key=TRUSTED_COOKIE,
            path=path,
            samesite="strict",
            secure=_cookie_secure(),
        )


def _set_pending_2fa_cookie(response: Response, user_id: int) -> None:
    expire = datetime.utcnow() + timedelta(minutes=_PENDING_2FA_MINUTES)
    token = jwt.encode(
        {"uid": user_id, "purpose": "pending_2fa", "exp": expire},
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    response.set_cookie(
        key=PENDING_2FA_COOKIE,
        value=token,
        max_age=_PENDING_2FA_MINUTES * 60,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        path=COOKIE_PATH,
    )


def _clear_pending_2fa_cookie(response: Response) -> None:
    for path in (COOKIE_PATH, "/"):
        response.delete_cookie(
            key=PENDING_2FA_COOKIE,
            path=path,
            samesite="lax",
            secure=_cookie_secure(),
        )


def _read_pending_2fa_user_id(raw: Optional[str]) -> Optional[int]:
    if not raw:
        return None
    try:
        payload = jwt.decode(raw, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if payload.get("purpose") != "pending_2fa":
            return None
        uid = payload.get("uid")
        return int(uid) if uid is not None else None
    except (JWTError, TypeError, ValueError):
        return None


def _bootstrap_secret_ok(header_secret: Optional[str]) -> bool:
    return constant_time_secret_equal(settings.ADMIN_BOOTSTRAP_SECRET, header_secret)


def _user_response(db_user: User) -> UserResponse:
    return UserResponse(
        id=db_user.id,
        username=db_user.username,
        email=db_user.email,
        is_active=bool(db_user.is_active),
        is_admin=bool(db_user.is_admin),
        is_operator=bool(getattr(db_user, "is_operator", False)),
        is_approved=bool(getattr(db_user, "is_approved", False)) or bool(db_user.is_admin),
        totp_enabled=bool(getattr(db_user, "totp_enabled", False)),
        has_password=bool(db_user.hashed_password),
        google_linked=bool(getattr(db_user, "google_sub", None)),
        email_verified=bool(getattr(db_user, "email_verified", False)),
        created_at=db_user.created_at,
    )


def _set_pending_profile_cookie(response: Response, user_id: int, email: str, suggested: str) -> None:
    expire = datetime.utcnow() + timedelta(minutes=_PENDING_PROFILE_MINUTES)
    token = jwt.encode(
        {
            "uid": user_id,
            "email": email,
            "suggested": suggested,
            "purpose": "pending_profile",
            "exp": expire,
        },
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    response.set_cookie(
        key=PENDING_PROFILE_COOKIE,
        value=token,
        max_age=_PENDING_PROFILE_MINUTES * 60,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        path=COOKIE_PATH,
    )


def _clear_pending_profile_cookie(response: Response) -> None:
    for path in (COOKIE_PATH, "/"):
        response.delete_cookie(
            key=PENDING_PROFILE_COOKIE,
            path=path,
            samesite="lax",
            secure=_cookie_secure(),
        )


def _read_pending_profile(raw: Optional[str]) -> Optional[dict]:
    if not raw:
        return None
    try:
        payload = jwt.decode(raw, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if payload.get("purpose") != "pending_profile":
            return None
        return {
            "uid": int(payload["uid"]),
            "email": str(payload.get("email") or ""),
            "suggested": str(payload.get("suggested") or ""),
        }
    except (JWTError, TypeError, ValueError, KeyError):
        return None


def _verify_link(raw_token: str) -> str:
    base = _frontend_base().rstrip("/")
    return f"{base}/api/v1/auth/verify-email?token={raw_token}"


def _reset_link(raw_token: str) -> str:
    base = _frontend_base().rstrip("/")
    return f"{base}/?auth=reset&token={raw_token}"


def _verify_totp(user: User, code: Optional[str]) -> bool:
    secret = CryptoService.decrypt(user.totp_secret or "")
    return bool(secret) and bool(code) and pyotp.TOTP(secret).verify(code, valid_window=1)


def _ua_label(request: Request) -> str:
    return ((request.headers.get("user-agent") or "")[:120]) or None


async def _finish_login(
    response: Response,
    session,
    user: User,
    request: Request,
    *,
    remember_device: bool,
    totp_just_ok: bool,
) -> Token:
    user.last_login = datetime.utcnow()
    if remember_device and totp_just_ok and getattr(user, "totp_enabled", False):
        raw, max_age = issue_trusted_device(session, user.id, label=_ua_label(request))
        session.commit()
        session.refresh(user)
        _set_trusted_cookie(response, raw, max_age)
    else:
        session.commit()
        session.refresh(user)
    access = await auth_service.create_access_token(user)
    _set_access_cookie(response, access)
    _clear_pending_2fa_cookie(response)
    return Token(access_token="", refresh_token="", token_type="cookie")


@router.get("/providers")
async def auth_providers():
    public_reg = bool(settings.SECURITY_ALLOW_PUBLIC_REGISTER)
    mail_ok = mail_configured()
    # Не показываем форму email-регистрации, пока Resend не настроен (иначе 503).
    password_register = public_reg and (
        mail_ok or not bool(settings.SECURITY_REQUIRE_EMAIL_VERIFY)
    )
    return {
        "google": google_oauth_configured(),
        "password_register": password_register,
        "mail": mail_ok,
        "email_verify_required": bool(settings.SECURITY_REQUIRE_EMAIL_VERIFY) and mail_ok,
        "trusted_device_days": int(settings.SECURITY_TRUSTED_DEVICE_DAYS),
    }


@router.post("/register")
async def register(
    user_data: UserCreateRequest,
    request: Request,
    response: Response,
    x_admin_bootstrap_secret: Annotated[Optional[str], Header()] = None,
):
    check_rate_limit(
        "register",
        client_ip_from_request(request),
        settings.SECURITY_REGISTER_MAX_ATTEMPTS,
        settings.SECURITY_REGISTER_WINDOW_SECONDS,
        "Слишком много попыток регистрации с этого адреса. Попробуйте позже.",
    )
    bootstrap_ok = _bootstrap_secret_ok(x_admin_bootstrap_secret)
    hashed_password = auth_service.get_password_hash(user_data.password)
    with db_service.get_session() as session:
        session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _BOOTSTRAP_LOCK_KEY})
        users_count = session.query(User).count()
        if not settings.SECURITY_ALLOW_PUBLIC_REGISTER:
            if not (bootstrap_ok and users_count == 0):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Регистрация паролем отключена. Войдите через Google.",
                )
        if settings.SECURITY_ALLOW_PUBLIC_REGISTER and settings.SECURITY_REQUIRE_EMAIL_VERIFY:
            if not mail_configured() and not (bootstrap_ok and users_count == 0):
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Почта не настроена — регистрация временно недоступна. Войдите через Google.",
                )
        email_norm = str(user_data.email).strip().lower()
        existing_user = session.query(User).filter(
            or_(User.username == user_data.username, User.email == email_norm)
        ).first()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Не удалось зарегистрироваться. Проверьте данные или войдите.",
            )
        make_admin = users_count == 0 and bootstrap_ok
        verified = make_admin or not (
            settings.SECURITY_REQUIRE_EMAIL_VERIFY and mail_configured()
        )
        approved = make_admin or not bool(settings.SECURITY_REQUIRE_ADMIN_APPROVAL)
        new_user = User(
            username=user_data.username,
            email=email_norm,
            hashed_password=hashed_password,
            is_active=True,
            is_admin=make_admin,
            is_approved=approved,
            token_version=0,
            email_verified=verified,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            last_login=datetime.utcnow() if verified else None,
        )
        session.add(new_user)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Не удалось зарегистрироваться. Проверьте данные или войдите.",
            ) from None
        session.refresh(new_user)

        if not verified:
            raw = issue_token(session, new_user.id, PURPOSE_VERIFY, hours=24)
            session.commit()
            send_verify_email(email_norm, _verify_link(raw), new_user.username)
            msg = "Мы отправили письмо со ссылкой. Подтвердите email, затем войдите."
            if not approved:
                msg += " После этого админ откроет доступ к генерациям."
            return {
                "ok": True,
                "needs_verification": True,
                "needs_approval": not approved,
                "message": msg,
            }

        access = await auth_service.create_access_token(new_user)
        _set_access_cookie(response, access)
        return {
            "ok": True,
            "needs_verification": False,
            "needs_approval": not approved,
            "access_token": "",
            "refresh_token": "",
            "token_type": "cookie",
            "message": None
            if approved
            else "Аккаунт создан. Генерации откроются после подтверждения администратором.",
        }


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
        raw_ident = user_data.username_or_email.strip()
        user = session.query(User).filter(
            or_(
                User.username == raw_ident,
                User.email == ident,
            )
        ).first()
        hashed = (
            user.hashed_password
            if user and user.hashed_password
            else auth_service.DUMMY_PASSWORD_HASH
        )
        password_ok = auth_service.verify_password(user_data.password, hashed)
        if not user or not user.hashed_password or not password_ok or not user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_LOGIN_FAIL)

        # Unverified / unapproved users may still log in — generate is gated separately.

        totp_just_ok = False
        if getattr(user, "totp_enabled", False):
            trusted = find_valid_trusted_device(
                session, user.id, request.cookies.get(TRUSTED_COOKIE)
            )
            if trusted:
                session.commit()
            else:
                if not _verify_totp(user, user_data.totp_code):
                    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_LOGIN_FAIL)
                totp_just_ok = True

        return await _finish_login(
            response,
            session,
            user,
            request,
            remember_device=bool(user_data.remember_device),
            totp_just_ok=totp_just_ok,
        )


@router.post("/logout")
async def logout(request: Request, response: Response):
    raw_trusted = request.cookies.get(TRUSTED_COOKIE)
    access = request.cookies.get(COOKIE_NAME)
    if access and raw_trusted:
        try:
            payload = await auth_service._user_from_token(access)
            with db_service.get_session() as session:
                revoke_trusted_device_by_token(session, payload.user_id, raw_trusted)
                session.commit()
        except Exception:
            pass
    _clear_access_cookie(response)
    _clear_trusted_cookie(response)
    _clear_pending_2fa_cookie(response)
    _clear_pending_profile_cookie(response)
    return {"ok": True}


@router.get("/verify-email")
async def verify_email(token: str, response: Response):
    with db_service.get_session() as session:
        uid = consume_token(session, token, PURPOSE_VERIFY)
        if uid is None:
            return _auth_redirect({"auth": "error", "reason": "verify_token"})
        user = session.query(User).filter(User.id == uid).first()
        if not user or not user.is_active:
            return _auth_redirect({"auth": "error", "reason": "verify_token"})
        user.email_verified = True
        session.commit()
        session.refresh(user)
        access = await auth_service.create_access_token(user)
    redirect = _auth_redirect({"auth": "verified"})
    _set_access_cookie(redirect, access)
    return redirect


@router.post("/resend-verification")
async def resend_verification(body: ResendVerifyRequest, request: Request):
    check_rate_limit(
        "resend-verify",
        client_ip_from_request(request),
        5,
        3600,
        "Слишком много писем. Попробуйте позже.",
    )
    # Always same response — no email enumeration.
    msg = {"ok": True, "message": "Если аккаунт существует и не подтверждён — письмо отправлено."}
    if not mail_configured():
        return msg
    email = str(body.email).strip().lower()
    with db_service.get_session() as session:
        user = session.query(User).filter(User.email == email).first()
        if user and user.is_active and not user.email_verified and user.hashed_password:
            raw = issue_token(session, user.id, PURPOSE_VERIFY, hours=24)
            session.commit()
            send_verify_email(email, _verify_link(raw), user.username)
    return msg


@router.post("/email", response_model=UserResponse)
async def update_email(
    body: UpdateEmailRequest,
    response: Response,
    user: Annotated[TokenPayload, Depends(auth_service.get_current_user)],
):
    """Set or change email; sends verification link. Required for legacy accounts."""
    email_norm = str(body.email).strip().lower()
    with db_service.get_session() as session:
        db_user = session.query(User).filter(User.id == user.user_id).first()
        if not db_user or not db_user.is_active:
            raise HTTPException(status_code=401, detail="Не авторизован")
        if db_user.hashed_password:
            if not body.current_password or not auth_service.verify_password(
                body.current_password, db_user.hashed_password
            ):
                raise HTTPException(status_code=401, detail="Неверный пароль")
        taken = (
            session.query(User)
            .filter(User.email == email_norm, User.id != db_user.id)
            .first()
        )
        if taken:
            raise HTTPException(status_code=409, detail="Этот email уже занят")
        db_user.email = email_norm
        db_user.email_verified = False
        db_user.updated_at = datetime.utcnow()
        if not mail_configured():
            session.commit()
            session.refresh(db_user)
            raise HTTPException(status_code=503, detail="Почта не настроена — напишите админу")
        raw = issue_token(session, db_user.id, PURPOSE_VERIFY, hours=24)
        session.commit()
        session.refresh(db_user)
        send_verify_email(email_norm, _verify_link(raw), db_user.username)
        return _user_response(db_user)


@router.delete("/me")
async def delete_my_account(
    body: DeleteAccountRequest,
    response: Response,
    user: Annotated[TokenPayload, Depends(auth_service.get_current_user)],
):
    with db_service.get_session() as session:
        db_user = session.query(User).filter(User.id == user.user_id).first()
        if not db_user:
            raise HTTPException(status_code=401, detail="Не авторизован")
        if db_user.is_admin:
            active_admins = (
                session.query(User)
                .filter(User.is_admin.is_(True), User.is_active.is_(True))
                .count()
            )
            if active_admins <= 1:
                raise HTTPException(
                    status_code=400,
                    detail="Нельзя удалить последнего админа — сначала назначьте другого",
                )
        if db_user.hashed_password:
            if not body.current_password or not auth_service.verify_password(
                body.current_password, db_user.hashed_password
            ):
                raise HTTPException(status_code=401, detail="Неверный пароль")
        else:
            if (body.confirm or "").strip() != db_user.username:
                raise HTTPException(
                    status_code=400,
                    detail="Для удаления введите своё имя пользователя в поле подтверждения",
                )
        uid = db_user.id
        username = db_user.username
        storage = MinioService()
        gens = session.query(Generation).filter(Generation.user_id == uid).all()
        for gen in gens:
            delete_generation_assets(storage, gen)
        session.query(AdminAuditLog).filter(
            or_(
                AdminAuditLog.actor_admin_id == uid,
                AdminAuditLog.target_user_id == uid,
            )
        ).delete(synchronize_session=False)
        session.query(Generation).filter(Generation.user_id == uid).delete(synchronize_session=False)
        session.delete(db_user)
        session.commit()
    _clear_access_cookie(response)
    _clear_trusted_cookie(response)
    _clear_pending_2fa_cookie(response)
    _clear_pending_profile_cookie(response)
    return {"ok": True, "message": f"Аккаунт {username} удалён"}


@router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordRequest, request: Request):
    check_rate_limit(
        "forgot-password",
        client_ip_from_request(request),
        5,
        3600,
        "Слишком много запросов. Попробуйте позже.",
    )
    msg = {"ok": True, "message": "Если аккаунт существует — письмо со ссылкой отправлено."}
    if not mail_configured():
        raise HTTPException(status_code=503, detail="Почта не настроена")
    email = str(body.email).strip().lower()
    with db_service.get_session() as session:
        user = session.query(User).filter(User.email == email).first()
        if user and user.is_active and user.hashed_password:
            raw = issue_token(session, user.id, PURPOSE_RESET, hours=1)
            session.commit()
            send_reset_password_email(email, _reset_link(raw), user.username)
    return msg


@router.post("/reset-password")
async def reset_password(body: ResetPasswordRequest, response: Response):
    with db_service.get_session() as session:
        uid = consume_token(session, body.token, PURPOSE_RESET)
        if uid is None:
            raise HTTPException(status_code=400, detail="Ссылка недействительна или устарела")
        user = session.query(User).filter(User.id == uid).first()
        if not user or not user.is_active:
            raise HTTPException(status_code=400, detail="Ссылка недействительна или устарела")
        user.hashed_password = auth_service.get_password_hash(body.new_password)
        user.email_verified = True
        user.token_version = int(getattr(user, "token_version", 0) or 0) + 1
        revoke_all_trusted_devices(session, user.id)
        session.commit()
        session.refresh(user)
        access = await auth_service.create_access_token(user)
        _set_access_cookie(response, access)
        _clear_trusted_cookie(response)
    return {"ok": True}


@router.get("/profile/pending")
async def profile_pending(request: Request):
    data = _read_pending_profile(request.cookies.get(PENDING_PROFILE_COOKIE))
    if not data:
        raise HTTPException(status_code=404, detail="Нет незавершённой регистрации")
    return {
        "email": data["email"],
        "suggested_username": data["suggested"],
    }


@router.post("/profile/complete", response_model=Token)
async def profile_complete(
    body: CompleteProfileRequest,
    request: Request,
    response: Response,
):
    data = _read_pending_profile(request.cookies.get(PENDING_PROFILE_COOKIE))
    if not data:
        raise HTTPException(status_code=401, detail="Сессия регистрации истекла — войдите снова")
    with db_service.get_session() as session:
        user = session.query(User).filter(User.id == data["uid"]).first()
        if not user or not user.is_active:
            _clear_pending_profile_cookie(response)
            raise HTTPException(status_code=401, detail="Сессия регистрации истекла — войдите снова")
        taken = session.query(User).filter(User.username == body.username, User.id != user.id).first()
        if taken:
            raise HTTPException(status_code=409, detail="Это имя уже занято")
        user.username = body.username
        user.email_verified = True
        session.commit()
        session.refresh(user)
        if getattr(user, "totp_enabled", False):
            trusted = find_valid_trusted_device(session, user.id, request.cookies.get(TRUSTED_COOKIE))
            if not trusted:
                _clear_pending_profile_cookie(response)
                _set_pending_2fa_cookie(response, user.id)
                return Token(access_token="", refresh_token="", token_type="pending_2fa")
        result = await _finish_login(
            response, session, user, request, remember_device=False, totp_just_ok=False
        )
        _clear_pending_profile_cookie(response)
        return result


@router.delete("/trusted-devices")
async def revoke_trusted_devices(
    response: Response,
    user: Annotated[TokenPayload, Depends(auth_service.get_current_user)],
):
    with db_service.get_session() as session:
        revoke_all_trusted_devices(session, user.user_id)
        session.commit()
    _clear_trusted_cookie(response)
    return {"ok": True, "revoked": True}


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(user: Annotated[TokenPayload, Depends(auth_service.get_current_user)]):
    with db_service.get_session() as session:
        db_user = session.query(User).filter(User.id == user.user_id).first()
        if not db_user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        return _user_response(db_user)


@router.post("/password")
async def change_password(
    body: PasswordChangeRequest,
    response: Response,
    user: Annotated[TokenPayload, Depends(auth_service.get_current_user)],
):
    check_rate_limit(
        "password-change",
        str(user.user_id),
        8,
        3600,
        "Слишком много смен пароля. Попробуйте позже.",
    )
    with db_service.get_session() as session:
        db_user = session.query(User).filter(User.id == user.user_id).first()
        if not db_user or not db_user.hashed_password:
            raise HTTPException(status_code=400, detail="У аккаунта нет пароля — вход через Google")
        if not auth_service.verify_password(body.current_password, db_user.hashed_password):
            raise HTTPException(status_code=400, detail="Текущий пароль не подошёл")
        db_user.hashed_password = auth_service.get_password_hash(body.new_password)
        db_user.token_version = int(getattr(db_user, "token_version", 0) or 0) + 1
        revoke_all_trusted_devices(session, db_user.id)
        session.commit()
        session.refresh(db_user)
        access = await auth_service.create_access_token(db_user)
        _set_access_cookie(response, access)
        _clear_trusted_cookie(response)
    return {"ok": True}


@router.post("/username")
async def change_username(
    body: UsernameChangeRequest,
    user: Annotated[TokenPayload, Depends(auth_service.get_current_user)],
):
    check_rate_limit(
        "username-change",
        str(user.user_id),
        8,
        3600,
        "Слишком много смен имени. Попробуйте позже.",
    )
    with db_service.get_session() as session:
        db_user = session.query(User).filter(User.id == user.user_id).first()
        if not db_user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        if db_user.hashed_password:
            if not auth_service.verify_password(body.current_password, db_user.hashed_password):
                raise HTTPException(status_code=400, detail="Текущий пароль не подошёл")
        elif not getattr(db_user, "google_sub", None):
            raise HTTPException(status_code=400, detail="Нельзя сменить имя")
        taken = session.query(User).filter(User.username == body.username, User.id != db_user.id).first()
        if taken:
            raise HTTPException(status_code=409, detail="Это имя уже занято")
        db_user.username = body.username
        session.commit()
        return _user_response(db_user)


@router.post("/totp/begin")
async def totp_begin(
    user: Annotated[TokenPayload, Depends(auth_service.get_current_user)],
):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Доступ только для админов")
    check_rate_limit(
        "totp-begin",
        str(user.user_id),
        settings.SECURITY_TOTP_MAX_ATTEMPTS,
        settings.SECURITY_TOTP_WINDOW_SECONDS,
        "Слишком много попыток настройки 2FA. Попробуйте позже.",
    )
    with db_service.get_session() as session:
        db_user = session.query(User).filter(User.id == user.user_id).first()
        if not db_user:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        if db_user.totp_enabled:
            raise HTTPException(status_code=400, detail="Двухфакторная аутентификация уже включена")
        secret = pyotp.random_base32()
        db_user.totp_secret = CryptoService.encrypt(secret)
        session.commit()
        uri = pyotp.TOTP(secret).provisioning_uri(name=db_user.username, issuer_name="Nano Banana")
        return {
            "otpauth_url": uri,
            "secret": secret,
            "qr_data_url": otpauth_qr_data_url(uri),
        }


@router.post("/totp/confirm")
async def totp_confirm(
    body: TotpConfirmRequest,
    user: Annotated[TokenPayload, Depends(auth_service.get_current_user)],
):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Доступ только для админов")
    check_rate_limit(
        "totp-confirm",
        str(user.user_id),
        settings.SECURITY_TOTP_MAX_ATTEMPTS,
        settings.SECURITY_TOTP_WINDOW_SECONDS,
        "Слишком много попыток подтверждения 2FA. Попробуйте позже.",
    )
    with db_service.get_session() as session:
        db_user = session.query(User).filter(User.id == user.user_id).first()
        if not db_user or not db_user.totp_secret:
            raise HTTPException(status_code=400, detail="Сначала начните настройку 2FA")
        if db_user.totp_enabled:
            raise HTTPException(status_code=400, detail="Двухфакторная аутентификация уже включена")
        secret = CryptoService.decrypt(db_user.totp_secret)
        if not secret or not pyotp.TOTP(secret).verify(body.code, valid_window=1):
            raise HTTPException(status_code=400, detail="Неверный код")
        db_user.totp_enabled = True
        session.commit()
        return {"ok": True, "totp_enabled": True}


@router.post("/totp/complete", response_model=Token)
async def totp_complete(
    body: TotpCompleteRequest,
    request: Request,
    response: Response,
):
    """Завершить Google (или иной) login после pending_2fa cookie."""
    check_rate_limit(
        "totp-complete",
        client_ip_from_request(request),
        settings.SECURITY_TOTP_MAX_ATTEMPTS,
        settings.SECURITY_TOTP_WINDOW_SECONDS,
        "Слишком много попыток 2FA. Попробуйте позже.",
    )
    uid = _read_pending_2fa_user_id(request.cookies.get(PENDING_2FA_COOKIE))
    if uid is None:
        raise HTTPException(status_code=401, detail="Сессия 2FA истекла — войдите снова")
    with db_service.get_session() as session:
        user = session.query(User).filter(User.id == uid).first()
        if not user or not user.is_active or not getattr(user, "totp_enabled", False):
            _clear_pending_2fa_cookie(response)
            raise HTTPException(status_code=401, detail="Сессия 2FA истекла — войдите снова")
        if not _verify_totp(user, body.code):
            raise HTTPException(status_code=401, detail="Неверный код")
        return await _finish_login(
            response,
            session,
            user,
            request,
            remember_device=bool(body.remember_device),
            totp_just_ok=True,
        )


@router.get("/google/start")
async def google_start(request: Request, response: Response):
    if not google_oauth_configured():
        raise HTTPException(status_code=503, detail="Вход через Google не настроен")
    check_rate_limit(
        "google-start",
        client_ip_from_request(request),
        30,
        300,
        "Слишком много попыток входа через Google.",
    )
    state = new_oauth_state()
    response = RedirectResponse(url=build_authorize_url(state), status_code=302)
    response.set_cookie(
        key=OAUTH_STATE_COOKIE,
        value=state,
        max_age=600,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        path=COOKIE_PATH,
    )
    return response


def _auth_redirect(query: dict) -> RedirectResponse:
    base = _frontend_base() or "/"
    qs = urlencode(query)
    url = f"{base}/?{qs}" if base != "/" else f"/?{qs}"
    return RedirectResponse(url=url, status_code=302)


@router.get("/google/callback")
async def google_callback(
    request: Request,
    response: Response,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
):
    if not google_oauth_configured():
        return _auth_redirect({"auth": "error", "reason": "google_disabled"})
    if error:
        return _auth_redirect({"auth": "error", "reason": "google_denied"})
    expected = request.cookies.get(OAUTH_STATE_COOKIE) or ""
    if not state or not expected or not constant_time_secret_equal(expected, state):
        return _auth_redirect({"auth": "error", "reason": "state"})
    if not code:
        return _auth_redirect({"auth": "error", "reason": "code"})

    check_rate_limit(
        "google-callback",
        client_ip_from_request(request),
        30,
        300,
        "Слишком много попыток входа через Google.",
    )

    try:
        info = exchange_code_for_userinfo(code)
    except ValueError:
        return _auth_redirect({"auth": "error", "reason": "token"})

    is_new_google_user = False
    with db_service.get_session() as session:
        user = session.query(User).filter(User.google_sub == info["sub"]).first()
        if not user:
            user = session.query(User).filter(User.email == info["email"]).first()
            if user:
                user.google_sub = info["sub"]
                user.email_verified = True
            else:
                base_name = username_from_google(info["email"], info.get("name") or "")
                suggested = unique_username(session, User, base_name)
                approved = not bool(settings.SECURITY_REQUIRE_ADMIN_APPROVAL)
                user = User(
                    username=suggested,
                    email=info["email"],
                    hashed_password=None,
                    is_active=True,
                    is_admin=False,
                    is_approved=approved,
                    token_version=0,
                    google_sub=info["sub"],
                    email_verified=True,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                    last_login=None,
                )
                session.add(user)
                is_new_google_user = True
            try:
                session.commit()
                session.refresh(user)
            except IntegrityError:
                session.rollback()
                return _auth_redirect({"auth": "error", "reason": "conflict"})

        if not user.is_active:
            return _auth_redirect({"auth": "error", "reason": "disabled"})

        # New Google account → confirm display name + show email before session.
        if is_new_google_user:
            suggested = user.username
            redirect = _auth_redirect({"auth": "complete_profile"})
            redirect.delete_cookie(
                OAUTH_STATE_COOKIE, path=COOKIE_PATH, samesite="lax", secure=_cookie_secure()
            )
            _set_pending_profile_cookie(redirect, user.id, user.email, suggested)
            return redirect

        if getattr(user, "totp_enabled", False):
            trusted = find_valid_trusted_device(
                session, user.id, request.cookies.get(TRUSTED_COOKIE)
            )
            if not trusted:
                session.commit()
                redirect = _auth_redirect({"auth": "totp_required"})
                redirect.delete_cookie(
                    OAUTH_STATE_COOKIE, path=COOKIE_PATH, samesite="lax", secure=_cookie_secure()
                )
                _set_pending_2fa_cookie(redirect, user.id)
                return redirect

        user.last_login = datetime.utcnow()
        user.email_verified = True
        if not user.google_sub:
            user.google_sub = info["sub"]
        session.commit()
        session.refresh(user)
        access = await auth_service.create_access_token(user)

    redirect = _auth_redirect({"auth": "ok"})
    redirect.delete_cookie(OAUTH_STATE_COOKIE, path=COOKIE_PATH, samesite="lax", secure=_cookie_secure())
    _set_access_cookie(redirect, access)
    return redirect
