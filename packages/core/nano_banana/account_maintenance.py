"""Periodic account hygiene: deactivate stale unverified users."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from nano_banana.config import settings
from nano_banana.db.models import User
from nano_banana.db.session import db_service
from nano_banana.trusted_device import revoke_all_trusted_devices

logger = logging.getLogger(__name__)


def deactivate_stale_unverified() -> dict:
    days = int(getattr(settings, "SECURITY_UNVERIFIED_INACTIVE_DAYS", 60) or 60)
    if days <= 0:
        return {"deactivated": 0, "days": days, "skipped": True}
    cutoff = datetime.utcnow() - timedelta(days=days)
    deactivated = 0
    with db_service.get_session() as session:
        rows = (
            session.query(User)
            .filter(User.is_active.is_(True))
            .filter(User.is_admin.is_(False))
            .filter(User.email_verified.is_(False))
            .all()
        )
        for user in rows:
            last = user.last_login or user.created_at
            if last is None or last > cutoff:
                continue
            user.is_active = False
            user.token_version = int(getattr(user, "token_version", 0) or 0) + 1
            revoke_all_trusted_devices(session, user.id)
            deactivated += 1
        if deactivated:
            session.commit()
    if deactivated:
        logger.info("[MAINT] deactivated %s stale unverified users (>%s days)", deactivated, days)
    return {"deactivated": deactivated, "days": days}
