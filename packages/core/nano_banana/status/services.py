"""Сводный статус Moonez + Google + пользователь для баннера."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from nano_banana.db.models import Generation
from nano_banana.db.session import db_service
import nano_banana.generation.runtime as runtime
from nano_banana.generation.keys import load_user_api_keys
from nano_banana.providers.models import DEFAULT_MODEL_ID, get_provider_for_model
from nano_banana.queue.jobs import get_job_queue
from nano_banana.status.google import get_google_gemini_status
from nano_banana.status.user import USER_STATUS_SAMPLE_SIZE, build_user_generation_status

USER_STATUS_LOOKBACK_HOURS = 24


def _load_user_generation_status(user_id: int) -> Dict[str, Any]:
    since = datetime.utcnow() - timedelta(hours=USER_STATUS_LOOKBACK_HOURS)
    with db_service.get_session() as session:
        rows = (
            session.query(Generation)
            .filter(
                Generation.user_id == user_id,
                Generation.created_at >= since,
                Generation.status.in_(("completed", "failed")),
            )
            .order_by(Generation.created_at.desc())
            .limit(USER_STATUS_SAMPLE_SIZE)
            .all()
        )
    payload_rows = []
    for gen in rows:
        meta = gen.generation_metadata or {}
        payload_rows.append(
            {
                "id": gen.id,
                "status": gen.status,
                "error": meta.get("error"),
                "provider": meta.get("provider"),
                "created_at": gen.created_at.isoformat() if gen.created_at else None,
            }
        )
    return build_user_generation_status(payload_rows)


def _merge_user(payload: Dict[str, Any], user_status: Dict[str, Any]) -> None:
    services = list(payload.get("services") or [])
    services.append(
        {
            "id": "your_account",
            "name": "Ваши генерации",
            "short_name": "Вы",
            "state": user_status.get("state"),
            "message": user_status.get("message"),
            "source": "user_history",
            "stats": {
                "recent_total": user_status.get("recent_total"),
                "recent_failed": user_status.get("recent_failed"),
                "recent_success": user_status.get("recent_success"),
                "fail_streak": user_status.get("fail_streak"),
            },
        }
    )
    payload["services"] = services
    payload["user"] = user_status
    user_state = str(user_status.get("state") or "unknown")
    overall_state = str(payload.get("state") or "unknown")
    overall_message = str(payload.get("message") or "")
    if user_state in ("degraded", "failing", "unavailable", "paused"):
        user_message = str(user_status.get("message") or "")
        if overall_state == "ok":
            payload["state"] = "degraded" if user_state == "failing" else user_state
            payload["message"] = user_message
        elif overall_state == "degraded" and user_message:
            payload["message"] = f"{overall_message} {user_message}"
        payload["can_generate"] = bool(payload.get("can_generate")) and bool(
            user_status.get("can_generate", True)
        )


def build_public_service_status(
    user_id: Optional[int] = None,
    *,
    include_internals: bool = False,
) -> Dict[str, Any]:
    google_status = get_google_gemini_status()
    reachable, probe_error = runtime.health_status()
    is_unavailable = not reachable or runtime.is_unavailable()
    is_paused = (not is_unavailable) and runtime.is_paused()
    is_runtime_degraded = runtime.is_upstream_degraded()
    google_incident = bool(google_status.get("has_active_incident"))
    active_google = (google_status.get("active_incidents") or [{}])[0] if google_incident else None
    snap = runtime.snapshot()
    queue_size = get_job_queue().queue_size() if include_internals else 0

    if is_unavailable:
        hub_state = "unavailable"
        hub_message = (
            "Moonez API временно недоступен. Попробуйте позже."
            if not include_internals
            else (
                probe_error or snap.get("last_unavailable_error") or (
                    "Moonez API недоступен: сервер провайдера не отвечает. "
                    "Проверьте панель https://moonez.ai и IP whitelist."
                )
            )
        )
        if include_internals:
            hub_message += runtime.format_duration_hint(
                runtime.duration_seconds("provider_unavailable_since", "last_unavailable_at"),
                "Недоступен уже",
            )
    elif is_paused:
        hub_state = "paused"
        hub_message = (
            "Moonez: генерация временно на паузе у провайдера."
            if not include_internals
            else (
                f"Moonez: проект на паузе у провайдера."
                f"{runtime.format_duration_hint(runtime.duration_seconds('project_paused_since', 'last_paused_at'), 'На паузе уже')} "
                f"Задач в очереди: {queue_size}."
            )
        )
    else:
        hub_state = "ok"
        hub_message = "Moonez API принимает запросы и создаёт задачи."

    if google_incident and active_google:
        gemini_state = "incident"
        gemini_message = active_google.get("title") or "Google сообщает об инциденте Gemini / Vertex AI."
        gemini_source = "google_official"
    elif is_runtime_degraded:
        gemini_state = "degraded"
        gemini_message = "Google upstream нестабилен — генерации могут не пройти."
        if include_internals:
            gemini_message = (
                "Google upstream возвращает internal error — генерации могут не пройти."
                + runtime.format_duration_hint(runtime.duration_seconds("upstream_degraded_since"), "Нестабильно уже")
            )
        gemini_source = "runtime_probe"
    elif google_status.get("fetch_ok"):
        gemini_state = "ok"
        gemini_message = "Официальных инцидентов Google Gemini нет."
        gemini_source = "google_official"
    else:
        gemini_state = "unknown"
        gemini_message = "Статус Google не проверен — смотрим только наш мониторинг."
        gemini_source = "runtime_probe"

    if is_unavailable or is_paused:
        overall_state = hub_state
        can_generate = False
        overall_message = hub_message
    elif gemini_state in ("incident", "degraded"):
        overall_state = "degraded"
        can_generate = True
        overall_message = (
            "Генерация возможна, но Google upstream нестабилен — попробуйте позже или повторите запрос."
        )
    else:
        overall_state = "ok"
        can_generate = True
        overall_message = "Все системы в норме — можно генерировать."

    payload = {
        "provider": "bananalab",
        "state": overall_state,
        "can_generate": can_generate,
        "message": overall_message,
        "updated_at": datetime.utcnow().isoformat(),
        "services": [
            {
                "id": "moonez",
                "name": "Moonez API",
                "short_name": "Moonez",
                "state": hub_state,
                "message": hub_message,
                "source": "health_probe",
            },
            {
                "id": "google_gemini",
                "name": "Google Gemini",
                "short_name": "Google AI",
                "state": gemini_state,
                "message": gemini_message,
                "source": gemini_source,
                "status_page_url": google_status.get("status_page_url"),
            },
        ],
        "google_status": {
            "has_active_incident": google_incident,
            "status_page_url": google_status.get("status_page_url"),
        },
    }
    if include_internals:
        payload["services"][1]["active_incidents"] = google_status.get("active_incidents") or []
        payload["google_status"].update(
            {
                "checked_at": google_status.get("checked_at"),
                "fetch_ok": google_status.get("fetch_ok"),
                "fetch_error": google_status.get("fetch_error"),
            }
        )
        payload["runtime"] = {
            "last_success_at": snap.get("last_success_at") or None,
            "last_upstream_error_at": snap.get("last_upstream_error_at") or None,
            "upstream_error_count": int(snap.get("upstream_error_count") or 0),
            "upstream_degraded": is_runtime_degraded,
            "queue_size": queue_size,
        }
    if user_id is not None:
        _merge_user(payload, _load_user_generation_status(user_id))
    return payload


def build_provider_status(user_id: int, model_name: Optional[str] = None) -> Dict[str, Any]:
    keys = load_user_api_keys(user_id)
    model = (model_name or DEFAULT_MODEL_ID).strip().lower()
    provider = get_provider_for_model(model, keys)
    snap = runtime.snapshot()
    queue_size = get_job_queue().queue_size()
    base_meta = {
        "paused_queue_size": queue_size,
        "last_paused_at": snap.get("last_paused_at") or None,
        "last_success_at": snap.get("last_success_at") or None,
        "has_replicate_key": bool(keys.get("replicate")),
        "has_bananalab_key": bool(keys.get("bananalab")),
        "has_openrouter_key": bool(keys.get("openrouter")),
        "model_name": model,
    }
    if not provider:
        return {
            "provider": "unknown",
            "state": "unknown",
            "can_generate": False,
            "message": "Для выбранной модели нет подходящего API ключа. Добавьте ключ в настройках.",
            **base_meta,
        }
    if provider == "replicate":
        return {
            "provider": "replicate",
            "state": "ok",
            "can_generate": True,
            "message": "Replicate: генерация доступна.",
            **base_meta,
        }
    if provider == "openrouter":
        return {
            "provider": "openrouter",
            "state": "ok",
            "can_generate": True,
            "message": "OpenRouter (GPT): генерация доступна.",
            **base_meta,
        }

    reachable, probe_error = runtime.health_status()
    is_unavailable = not reachable or runtime.is_unavailable()
    is_paused = (not is_unavailable) and runtime.is_paused()
    paused_duration = runtime.duration_seconds("project_paused_since", "last_paused_at") if is_paused else None
    unavailable_duration = (
        runtime.duration_seconds("provider_unavailable_since", "last_unavailable_at") if is_unavailable else None
    )
    if is_unavailable:
        state = "unavailable"
        message = (probe_error or snap.get("last_unavailable_error") or (
            "Moonez API недоступен: сервер провайдера не отвечает. "
            "Проверьте панель https://moonez.ai и IP whitelist."
        )) + runtime.format_duration_hint(unavailable_duration, "Недоступен уже")
    elif is_paused:
        state = "paused"
        message = (
            f"Moonez: проект на паузе у провайдера."
            f"{runtime.format_duration_hint(paused_duration, 'На паузе уже')} "
            f"Задач в очереди: {queue_size}. Автоповтор включён."
        )
    elif runtime.is_upstream_degraded() or get_google_gemini_status().get("has_active_incident"):
        state = "degraded"
        message = (
            "Google Gemini upstream нестабилен — генерации могут падать."
            + runtime.format_duration_hint(runtime.duration_seconds("upstream_degraded_since"), "Нестабильно уже")
        )
    else:
        state = "ok"
        message = "Moonez: генерация доступна."
    return {
        "provider": "bananalab",
        "state": state,
        "can_generate": state in ("ok", "degraded"),
        "message": message,
        "paused_queue_size": queue_size,
        "last_paused_error": snap.get("last_paused_error") or None,
        "last_unavailable_at": snap.get("last_unavailable_at") or None,
        "last_unavailable_error": snap.get("last_unavailable_error") or None,
        "paused_since": snap.get("project_paused_since") or None,
        "paused_duration_seconds": paused_duration,
        "unavailable_since": snap.get("provider_unavailable_since") or None,
        "unavailable_duration_seconds": unavailable_duration,
        **base_meta,
    }
