"""Google OAuth (openid/email/profile) helpers."""
from __future__ import annotations

import logging
import re
import secrets
from typing import Any, Dict
from urllib.parse import urlencode

import requests

from nano_banana.config import settings
from nano_banana.schemas import normalize_username

logger = logging.getLogger(__name__)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
OAUTH_STATE_COOKIE = "nb_oauth_state"
PENDING_2FA_COOKIE = "nb_pending_2fa"
SCOPES = "openid email profile"


def google_oauth_configured() -> bool:
    return bool(
        (settings.GOOGLE_OAUTH_CLIENT_ID or "").strip()
        and (settings.GOOGLE_OAUTH_CLIENT_SECRET or "").strip()
        and (settings.GOOGLE_OAUTH_REDIRECT_URI or "").strip()
    )


def build_authorize_url(state: str) -> str:
    params = {
        "client_id": settings.GOOGLE_OAUTH_CLIENT_ID.strip(),
        "redirect_uri": settings.GOOGLE_OAUTH_REDIRECT_URI.strip(),
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
        "access_type": "online",
        "include_granted_scopes": "true",
        "prompt": "select_account",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def new_oauth_state() -> str:
    return secrets.token_urlsafe(24)


def exchange_code_for_userinfo(code: str) -> Dict[str, Any]:
    token_resp = requests.post(
        GOOGLE_TOKEN_URL,
        data={
            "code": code,
            "client_id": settings.GOOGLE_OAUTH_CLIENT_ID.strip(),
            "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET.strip(),
            "redirect_uri": settings.GOOGLE_OAUTH_REDIRECT_URI.strip(),
            "grant_type": "authorization_code",
        },
        timeout=20,
    )
    if token_resp.status_code != 200:
        logger.warning("[GOOGLE] token exchange failed: %s", token_resp.status_code)
        raise ValueError("Не удалось обменять код Google")
    access = (token_resp.json() or {}).get("access_token")
    if not access:
        raise ValueError("Google не вернул access_token")
    info_resp = requests.get(
        GOOGLE_USERINFO_URL,
        headers={"Authorization": f"Bearer {access}"},
        timeout=20,
    )
    if info_resp.status_code != 200:
        raise ValueError("Не удалось получить профиль Google")
    data = info_resp.json() or {}
    sub = str(data.get("sub") or "").strip()
    email = str(data.get("email") or "").strip().lower()
    if not sub or not email:
        raise ValueError("Google не вернул email/sub")
    if data.get("email_verified") is False:
        raise ValueError("Email Google не подтверждён")
    return {
        "sub": sub,
        "email": email,
        "name": str(data.get("name") or "").strip(),
        "email_verified": True,
    }


_SAFE_USER_RE = re.compile(r"[^\w.-]", re.UNICODE)


def username_from_google(email: str, display_name: str = "") -> str:
    local = (email or "").split("@", 1)[0]
    raw = _SAFE_USER_RE.sub("", (display_name or local or "user").replace(" ", "_"))
    raw = raw.strip(".-_") or "user"
    if len(raw) < 3:
        raw = (raw + "user")[:32]
    raw = raw[:32]
    try:
        return normalize_username(raw)
    except ValueError:
        return normalize_username(("u_" + raw)[:32].lstrip(".-_") or "user01")


def unique_username(session, User, base: str) -> str:
    candidate = base
    n = 0
    while session.query(User).filter(User.username == candidate).first():
        n += 1
        suffix = f"_{n}"
        candidate = (base[: max(3, 32 - len(suffix))] + suffix)[:32]
        if n > 9999:
            candidate = f"user{secrets.token_hex(4)}"
            break
    return candidate
