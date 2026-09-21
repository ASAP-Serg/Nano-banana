"""Состояние Moonez в Redis (пауза / недоступность / upstream), общее для API и worker."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from nano_banana.providers.errors import (
    is_bananalab_paused_message,
    is_bananalab_unavailable_message,
)
from nano_banana.providers.moonez import BananalabService
from nano_banana.queue.jobs import get_job_queue

BANANALAB_HEALTH_PROBE_TTL_SECONDS = 45
BANANALAB_UPSTREAM_DEGRADED_WINDOW_SECONDS = 1800
BANANALAB_UPSTREAM_DEGRADED_MIN_ERRORS = 2


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def _state() -> Dict[str, Any]:
    return get_job_queue().get_provider_state()


def _set(**fields: Any) -> None:
    get_job_queue().set_provider_state(fields)


def _get(key: str) -> Optional[str]:
    value = _state().get(key)
    if value in (None, "", "None"):
        return None
    return value


def mark_paused(error_message: str) -> None:
    now = _now_iso()
    fields = {"last_paused_at": now, "last_paused_error": error_message}
    if not _get("project_paused_since"):
        fields["project_paused_since"] = now
    _set(**fields)


def clear_paused() -> None:
    _set(project_paused_since="", last_paused_error="")


def mark_unavailable(error_message: str) -> None:
    now = _now_iso()
    fields = {"last_unavailable_at": now, "last_unavailable_error": error_message}
    if not _get("provider_unavailable_since"):
        fields["provider_unavailable_since"] = now
    _set(**fields)


def clear_unavailable() -> None:
    _set(provider_unavailable_since="", last_unavailable_error="")


def mark_success() -> None:
    _set(last_success_at=_now_iso())
    clear_paused()
    clear_unavailable()
    clear_upstream_degraded()


def mark_upstream_degraded(error_message: str) -> None:
    now = _now_iso()
    count = int(_get("upstream_error_count") or 0) + 1
    fields = {
        "last_upstream_error_at": now,
        "last_upstream_error_message": (error_message or "")[:500],
        "upstream_error_count": str(count),
    }
    if not _get("upstream_degraded_since"):
        fields["upstream_degraded_since"] = now
    _set(**fields)


def clear_upstream_degraded() -> None:
    _set(upstream_error_count="0", upstream_degraded_since="", last_upstream_error_message="")


def health_status() -> tuple[bool, Optional[str]]:
    import time

    now_ts = time.time()
    probe_at = _get("health_probe_at")
    if probe_at is not None:
        try:
            if (now_ts - float(probe_at)) < BANANALAB_HEALTH_PROBE_TTL_SECONDS:
                ok = _get("health_probe_ok") == "1"
                return ok, _get("health_probe_error")
        except ValueError:
            pass
    reachable, probe_error = BananalabService.probe_reachable()
    _set(
        health_probe_at=str(now_ts),
        health_probe_ok="1" if reachable else "0",
        health_probe_error=probe_error or "",
    )
    if not reachable:
        mark_unavailable(probe_error or "Moonez API недоступен.")
    return reachable, probe_error


def is_unavailable() -> bool:
    last_error = _get("last_unavailable_error") or ""
    if not is_bananalab_unavailable_message(last_error):
        return False
    last_unavailable = _get("last_unavailable_at")
    last_success = _get("last_success_at")
    if last_unavailable and (not last_success or str(last_success) < str(last_unavailable)):
        return True
    return False


def is_paused() -> bool:
    last_error = _get("last_paused_error") or ""
    last_paused = _get("last_paused_at")
    last_success = _get("last_success_at")
    if is_bananalab_paused_message(last_error):
        if last_paused and (not last_success or str(last_success) < str(last_paused)):
            return True
    queue_size = get_job_queue().queue_size()
    if queue_size > 0 and last_paused:
        if not last_success or str(last_success) < str(last_paused):
            return True
    return False


def is_upstream_degraded() -> bool:
    last_upstream = _get("last_upstream_error_at")
    last_success = _get("last_success_at")
    error_count = int(_get("upstream_error_count") or 0)
    if error_count < BANANALAB_UPSTREAM_DEGRADED_MIN_ERRORS or not last_upstream:
        return False
    if last_success and str(last_success) >= str(last_upstream):
        return False
    try:
        started = datetime.fromisoformat(str(last_upstream))
        age = (datetime.utcnow() - started).total_seconds()
    except ValueError:
        return False
    return age <= BANANALAB_UPSTREAM_DEGRADED_WINDOW_SECONDS


def duration_seconds(since_key: str, fallback_key: Optional[str] = None) -> Optional[int]:
    since = _get(since_key) or (_get(fallback_key) if fallback_key else None)
    if not since:
        return None
    try:
        started = datetime.fromisoformat(str(since))
        return max(0, int((datetime.utcnow() - started).total_seconds()))
    except ValueError:
        return None


def format_duration_hint(total_seconds: Optional[int], prefix: str) -> str:
    if total_seconds is None:
        return ""
    hours, rem = divmod(total_seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f" {prefix} {hours} ч {minutes} мин."
    if minutes:
        return f" {prefix} {minutes} мин {seconds} сек."
    return f" {prefix} {seconds} сек."


def snapshot() -> Dict[str, Any]:
    return _state()
