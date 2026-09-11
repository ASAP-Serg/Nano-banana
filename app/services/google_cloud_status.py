"""
Публичный статус Google Cloud / Gemini с status.cloud.google.com/incidents.json.
Кэшируется — не дергаем Google на каждый запрос пользователя.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

_INCIDENTS_URL = "https://status.cloud.google.com/incidents.json"
_CACHE_TTL_SECONDS = 300
_GEMINI_KEYWORDS = (
    "gemini",
    "vertex ai",
    "generative language",
    "generativelanguage",
    "imagen",
    "nano banana",
)

_cache: Dict[str, Any] = {
    "checked_at": None,
    "ok": False,
    "error": None,
    "active_incidents": [],
    "recent_incidents": [],
}


def _parse_iso_dt(value: Optional[str]) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _incident_matches_gemini(incident: Dict[str, Any]) -> bool:
    blob = " ".join(
        str(incident.get(key) or "")
        for key in ("external_desc", "detail", "status_impact", "service_name")
    ).lower()
    return any(keyword in blob for keyword in _GEMINI_KEYWORDS)


def _normalize_incident(incident: Dict[str, Any]) -> Dict[str, Any]:
    begin = incident.get("begin")
    end = incident.get("end")
    return {
        "id": incident.get("id"),
        "title": (incident.get("external_desc") or "Инцидент Google Cloud")[:240],
        "begin": begin,
        "end": end,
        "is_active": _parse_iso_dt(end) is None or (
            _parse_iso_dt(end) is not None and _parse_iso_dt(end) > datetime.now(timezone.utc)
        ),
        "uri": incident.get("uri") or "https://status.cloud.google.com/",
    }


def _fetch_incidents() -> List[Dict[str, Any]]:
    resp = requests.get(_INCIDENTS_URL, timeout=12)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def get_google_gemini_status(force_refresh: bool = False) -> Dict[str, Any]:
    """Возвращает официальный статус Gemini/Vertex из Google Cloud Status."""
    now_ts = time.time()
    checked_at = _cache.get("checked_at")
    if (
        not force_refresh
        and checked_at is not None
        and (now_ts - float(checked_at)) < _CACHE_TTL_SECONDS
    ):
        return {
            "source": "google_cloud_status",
            "checked_at": _cache.get("checked_at_iso"),
            "fetch_ok": bool(_cache.get("ok")),
            "fetch_error": _cache.get("error"),
            "has_active_incident": bool(_cache.get("active_incidents")),
            "active_incidents": list(_cache.get("active_incidents") or []),
            "recent_incidents": list(_cache.get("recent_incidents") or []),
            "status_page_url": "https://status.cloud.google.com/",
        }

    active: List[Dict[str, Any]] = []
    recent: List[Dict[str, Any]] = []
    fetch_ok = False
    fetch_error: Optional[str] = None

    try:
        raw_incidents = _fetch_incidents()
        fetch_ok = True
        now = datetime.now(timezone.utc)
        for item in raw_incidents:
            if not _incident_matches_gemini(item):
                continue
            normalized = _normalize_incident(item)
            begin_dt = _parse_iso_dt(normalized.get("begin"))
            if begin_dt and (now - begin_dt).total_seconds() > 14 * 86400:
                continue
            if normalized.get("is_active"):
                active.append(normalized)
            else:
                recent.append(normalized)
        active.sort(key=lambda x: str(x.get("begin") or ""), reverse=True)
        recent.sort(key=lambda x: str(x.get("begin") or ""), reverse=True)
        recent = recent[:3]
    except Exception as exc:
        fetch_error = str(exc)[:300]
        logger.warning("[GOOGLE_STATUS] Не удалось получить incidents.json: %s", fetch_error)

    checked_iso = datetime.now(timezone.utc).isoformat()
    _cache["checked_at"] = now_ts
    _cache["checked_at_iso"] = checked_iso
    _cache["ok"] = fetch_ok
    _cache["error"] = fetch_error
    _cache["active_incidents"] = active
    _cache["recent_incidents"] = recent

    return {
        "source": "google_cloud_status",
        "checked_at": checked_iso,
        "fetch_ok": fetch_ok,
        "fetch_error": fetch_error,
        "has_active_incident": bool(active),
        "active_incidents": active,
        "recent_incidents": recent,
        "status_page_url": "https://status.cloud.google.com/",
    }
