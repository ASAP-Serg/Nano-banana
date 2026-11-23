"""Periodic account hygiene: purge / deactivate unverified registrations."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import or_

from nano_banana.config import settings
from nano_banana.db.models import AdminAuditLog, AuthEmailToken, Generation, TrustedDevice, User
from nano_banana.db.session import db_service
from nano_banana.trusted_device import revoke_all_trusted_devices

logger = logging.getLogger(__name__)


def unverified_purge_hours() -> int:
    return max(0, int(getattr(settings, "SECURITY_UNVERIFIED_PURGE_HOURS", 1) or 0))


def purge_unverified_pending() -> dict:
    """Delete password signups that never confirmed email (spam stubs).

    Targets: email_verified=False, not admin, inactive (waiting for code) or
    never logged in — older than SECURITY_UNVERIFIED_PURGE_HOURS.
    """
    hours = unverified_purge_hours()
    if hours <= 0:
        return {"deleted": 0, "hours": hours, "skipped": True}
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    deleted = 0
    with db_service.get_session() as session:
        rows = (
            session.query(User)
            .filter(User.email_verified.is_(False))
            .filter(User.is_admin.is_(False))
            .filter(User.is_superadmin.is_(False))
            .filter(User.hashed_password.isnot(None))
            .filter(User.created_at < cutoff)
            .filter(
                or_(
                    User.is_active.is_(False),
                    User.last_login.is_(None),
                )
            )
            .all()
        )
        for user in rows:
            uid = int(user.id)
            session.query(AuthEmailToken).filter(AuthEmailToken.user_id == uid).delete(
                synchronize_session=False
            )
            session.query(TrustedDevice).filter(TrustedDevice.user_id == uid).delete(
                synchronize_session=False
            )
            session.query(Generation).filter(Generation.user_id == uid).delete(
                synchronize_session=False
            )
            session.query(AdminAuditLog).filter(
                or_(
                    AdminAuditLog.actor_admin_id == uid,
                    AdminAuditLog.target_user_id == uid,
                )
            ).delete(synchronize_session=False)
            session.delete(user)
            deleted += 1
        if deleted:
            session.commit()
    if deleted:
        logger.info(
            "[MAINT] purged %s unverified pending users (>%s h without confirm)",
            deleted,
            hours,
        )
    return {"deleted": deleted, "hours": hours}


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
