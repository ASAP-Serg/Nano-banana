"""Who may run sensitive actions (generate, API keys, etc.)."""
from __future__ import annotations

from typing import Optional, Tuple

from fastapi import HTTPException

from nano_banana.config import settings


def email_ok_for_generate(user) -> bool:
    if getattr(user, "is_admin", False):
        return True
    if getattr(user, "google_sub", None):
        return True
    if not settings.SECURITY_REQUIRE_EMAIL_VERIFY:
        return True
    return bool(getattr(user, "email_verified", False))


def approval_ok_for_generate(user) -> bool:
    if getattr(user, "is_admin", False):
        return True
    if not settings.SECURITY_REQUIRE_ADMIN_APPROVAL:
        return True
    return bool(getattr(user, "is_approved", False))


def generate_block_reason(user) -> Optional[str]:
    """Return human-readable block reason, or None if allowed."""
    if not bool(getattr(user, "is_active", True)):
        return "Аккаунт отключён."
    if not email_ok_for_generate(user):
        return "Подтвердите email, прежде чем запускать генерации."
    if not approval_ok_for_generate(user):
        return "Аккаунт ждёт подтверждения администратором. Генерации пока недоступны."
    return None


def access_flags(user) -> Tuple[bool, bool]:
    return email_ok_for_generate(user), approval_ok_for_generate(user)


def require_sensitive_access(user) -> None:
    """Raise 403 unless user may use generate / store provider API keys."""
    reason = generate_block_reason(user)
    if reason:
        raise HTTPException(status_code=403, detail=reason)
