"""Статус генераций конкретного пользователя по последним попыткам в БД."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.bananalab_response import (
    is_bananalab_paused_message,
    is_bananalab_unavailable_message,
    is_bananalab_upstream_internal_error_message,
    is_bananalab_upstream_no_image_message,
    is_policy_block_error,
)

USER_STATUS_SAMPLE_SIZE = 8


def classify_generation_error(status: str, error_text: Optional[str]) -> str:
    err = str(error_text or "")
    if status == "completed":
        return "success"
    if is_bananalab_upstream_internal_error_message(err):
        return "upstream_internal"
    if is_bananalab_upstream_no_image_message(err):
        return "upstream_no_image"
    if is_policy_block_error(err):
        return "policy"
    if is_bananalab_paused_message(err):
        return "paused"
    if is_bananalab_unavailable_message(err):
        return "unavailable"
    if status == "failed":
        return "other_failure"
    return "unknown"


def build_user_generation_status(
    generations: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    generations — newest first:
    {status, error, provider, created_at, id}
    """
    finished = [
        g
        for g in generations
        if str(g.get("status") or "") in ("completed", "failed")
    ][:USER_STATUS_SAMPLE_SIZE]

    if not finished:
        return {
            "state": "unknown",
            "can_generate": True,
            "message": "Нет недавних генераций — персональный статус появится после первой попытки.",
            "recent_total": 0,
            "recent_failed": 0,
            "recent_success": 0,
            "fail_streak": 0,
            "last_error_kind": None,
            "last_generation_id": None,
            "source": "user_history",
        }

    recent_failed = sum(1 for g in finished if g.get("status") == "failed")
    recent_success = sum(1 for g in finished if g.get("status") == "completed")

    fail_streak = 0
    last_error_kind: Optional[str] = None
    for gen in finished:
        if gen.get("status") == "completed":
            break
        fail_streak += 1
        if last_error_kind is None:
            last_error_kind = classify_generation_error(
                str(gen.get("status") or ""),
                gen.get("error"),
            )

    latest = finished[0]
    latest_kind = classify_generation_error(
        str(latest.get("status") or ""),
        latest.get("error"),
    )

    if latest_kind == "success":
        state = "ok"
        message = "Ваша последняя генерация прошла успешно."
    elif fail_streak >= 2 and last_error_kind == "upstream_internal":
        state = "degraded"
        message = (
            f"У вас {fail_streak} последних генераций подряд не прошли "
            f"(Google upstream error). Это может быть общий сбой, не только у вас."
        )
    elif fail_streak >= 2 and last_error_kind == "upstream_no_image":
        state = "degraded"
        message = (
            f"У вас {fail_streak} последних генераций подряд без результата "
            f"(upstream no image). Попробуйте упростить промпт или повторить позже."
        )
    elif latest_kind == "policy":
        state = "failing"
        message = "Последняя генерация заблокирована фильтром контента — переформулируйте промпт."
    elif latest_kind == "paused":
        state = "paused"
        message = "Последняя генерация остановлена: BananaHub на паузе."
    elif latest_kind == "unavailable":
        state = "unavailable"
        message = "Последняя генерация не прошла: BananaHub API был недоступен."
    elif fail_streak >= 1:
        state = "degraded"
        message = "Последняя генерация не прошла — попробуйте ещё раз или смените промпт."
    else:
        state = "unknown"
        message = "Не удалось определить статус ваших последних генераций."

    can_generate = state in ("ok", "degraded", "unknown", "failing")

    return {
        "state": state,
        "can_generate": can_generate,
        "message": message,
        "recent_total": len(finished),
        "recent_failed": recent_failed,
        "recent_success": recent_success,
        "fail_streak": fail_streak,
        "last_error_kind": last_error_kind or latest_kind,
        "last_generation_id": latest.get("id"),
        "source": "user_history",
    }
