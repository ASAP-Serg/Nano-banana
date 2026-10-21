"""Trusted-device cookies for skipping TOTP on known browsers."""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional, Tuple

from nano_banana.config import settings
from nano_banana.db.models import TrustedDevice
from nano_banana.db.session import db_service

TRUSTED_COOKIE = "nb_trusted_device"
COOKIE_PATH = "/api"


def _hash_token(raw: str) -> str:
    material = f"{settings.SECRET_KEY}:trusted:{raw}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def issue_trusted_device(
    session,
    user_id: int,
    *,
    label: Optional[str] = None,
) -> Tuple[str, int]:
    """Create DB row + return (raw_token, max_age_seconds)."""
    days = max(1, int(settings.SECURITY_TRUSTED_DEVICE_DAYS))
    raw = secrets.token_urlsafe(32)
    now = datetime.utcnow()
    row = TrustedDevice(
        user_id=user_id,
        token_hash=_hash_token(raw),
        label=(label or "")[:120] or None,
        expires_at=now + timedelta(days=days),
        created_at=now,
        last_used_at=now,
    )
    session.add(row)
    return raw, days * 86400


def find_valid_trusted_device(session, user_id: int, raw_token: Optional[str]) -> Optional[TrustedDevice]:
    if not raw_token or not str(raw_token).strip():
        return None
    token_hash = _hash_token(str(raw_token).strip())
    now = datetime.utcnow()
    row = (
        session.query(TrustedDevice)
        .filter(
            TrustedDevice.user_id == user_id,
            TrustedDevice.token_hash == token_hash,
            TrustedDevice.expires_at > now,
        )
        .first()
    )
    if row:
        row.last_used_at = now
    return row


def revoke_all_trusted_devices(session, user_id: int) -> int:
    return (
        session.query(TrustedDevice)
        .filter(TrustedDevice.user_id == user_id)
        .delete(synchronize_session=False)
    )


def revoke_trusted_device_by_token(session, user_id: int, raw_token: Optional[str]) -> bool:
    if not raw_token:
        return False
    token_hash = _hash_token(str(raw_token).strip())
    deleted = (
        session.query(TrustedDevice)
        .filter(TrustedDevice.user_id == user_id, TrustedDevice.token_hash == token_hash)
        .delete(synchronize_session=False)
    )
    return deleted > 0


def purge_expired_trusted_devices(session) -> int:
    now = datetime.utcnow()
    return (
        session.query(TrustedDevice)
        .filter(TrustedDevice.expires_at <= now)
        .delete(synchronize_session=False)
    )


def revoke_all_for_user_commit(user_id: int) -> None:
    with db_service.get_session() as session:
        revoke_all_trusted_devices(session, user_id)
        session.commit()
