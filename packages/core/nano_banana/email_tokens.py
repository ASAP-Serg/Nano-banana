"""One-time email verification / password-reset tokens."""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional

from nano_banana.config import settings
from nano_banana.db.models import AuthEmailToken

PURPOSE_VERIFY = "verify"
PURPOSE_RESET = "reset"


def _hash(raw: str) -> str:
    material = f"{settings.SECRET_KEY}:mail:{raw}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def issue_token(session, user_id: int, purpose: str, *, hours: int) -> str:
    # Invalidate previous unused tokens of same purpose.
    session.query(AuthEmailToken).filter(
        AuthEmailToken.user_id == user_id,
        AuthEmailToken.purpose == purpose,
        AuthEmailToken.used_at.is_(None),
    ).delete(synchronize_session=False)
    raw = secrets.token_urlsafe(32)
    now = datetime.utcnow()
    session.add(
        AuthEmailToken(
            user_id=user_id,
            purpose=purpose,
            token_hash=_hash(raw),
            expires_at=now + timedelta(hours=hours),
            created_at=now,
        )
    )
    return raw


def consume_token(session, raw: str, purpose: str) -> Optional[int]:
    """Atomically consume a one-time token (row lock + used_at)."""
    if not raw or not str(raw).strip():
        return None
    now = datetime.utcnow()
    row = (
        session.query(AuthEmailToken)
        .filter(
            AuthEmailToken.token_hash == _hash(str(raw).strip()),
            AuthEmailToken.purpose == purpose,
            AuthEmailToken.used_at.is_(None),
            AuthEmailToken.expires_at > now,
        )
        .with_for_update()
        .first()
    )
    if not row:
        return None
    # Second guard against races across backends that ignore FOR UPDATE.
    if row.used_at is not None:
        return None
    row.used_at = now
    session.flush()
    return int(row.user_id)
