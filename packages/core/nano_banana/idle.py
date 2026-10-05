"""Idle-account rules for the admin user list (manual cleanup, no auto-delete)."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

IDLE_GENERATION_DAYS = 60


def is_generation_idle(
    created_at: Optional[datetime],
    last_generated_at: Optional[datetime],
    *,
    now: Optional[datetime] = None,
    days: int = IDLE_GENERATION_DAYS,
) -> bool:
    """True if the account has not generated for `days` (never-generated uses created_at)."""
    moment = now or datetime.utcnow()
    cutoff = moment - timedelta(days=days)
    activity = last_generated_at or created_at
    if activity is None:
        return True
    return activity <= cutoff
