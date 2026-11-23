"""Browser error intake — rate-limited, truncated, stored in Redis for admin peek."""

from __future__ import annotations

import json
import logging
import time
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from fastapi import HTTPException

from nano_banana.auth import auth_service
from nano_banana.queue.jobs import get_job_queue
from nano_banana.rate_limit import check_rate_limit, client_ip_from_request
from nano_banana.tokens import TokenPayload

logger = logging.getLogger("nano_banana.client_errors")

router = APIRouter(prefix="/client-errors", tags=["client-errors"])

_REDIS_KEY = "nano_banana:client_errors"
_MAX_STORE = 500
_MAX_MSG = 800
_MAX_STACK = 4000


class ClientErrorIn(BaseModel):
    message: str = Field(default="", max_length=_MAX_MSG)
    stack: str = Field(default="", max_length=_MAX_STACK)
    source: str = Field(default="error", max_length=40)
    url: str = Field(default="", max_length=500)
    path: str = Field(default="", max_length=300)
    status: Optional[int] = None
    user_agent: str = Field(default="", max_length=300)


def _clip(value: str, n: int) -> str:
    text = (value or "").strip()
    if len(text) <= n:
        return text
    return text[: n - 1] + "…"


@router.post("")
async def report_client_error(body: ClientErrorIn, request: Request):
    ip = client_ip_from_request(request) or "unknown"
    check_rate_limit(
        "client-errors",
        ip,
        20,
        60,
        "Слишком много отчётов об ошибках.",
    )
    payload: dict[str, Any] = {
        "ts": time.time(),
        "ip": ip,
        "message": _clip(body.message, _MAX_MSG),
        "stack": _clip(body.stack, _MAX_STACK),
        "source": _clip(body.source, 40) or "error",
        "url": _clip(body.url, 500),
        "path": _clip(body.path, 300),
        "status": body.status,
        "ua": _clip(body.user_agent or (request.headers.get("user-agent") or ""), 300),
    }
    logger.warning(
        "[BROWSER] source=%s status=%s path=%s msg=%s",
        payload["source"],
        payload["status"],
        payload["path"] or payload["url"],
        payload["message"][:200],
    )
    try:
        client = get_job_queue().client
        client.lpush(_REDIS_KEY, json.dumps(payload, ensure_ascii=False))
        client.ltrim(_REDIS_KEY, 0, _MAX_STORE - 1)
        client.expire(_REDIS_KEY, 7 * 24 * 3600)
    except Exception:
        logger.exception("Failed to store client error in Redis")
    return {"ok": True}


def _require_admin_totp(user: TokenPayload) -> None:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Доступ только для админов")
    if not user.totp_enabled:
        raise HTTPException(status_code=403, detail="Включите двухфакторную аутентификацию")


@router.get("/recent")
async def recent_client_errors(
    user: Annotated[TokenPayload, Depends(auth_service.get_current_user)],
    limit: int = 50,
):
    _require_admin_totp(user)
    limit = max(1, min(int(limit or 50), 200))
    try:
        client = get_job_queue().client
        rows = client.lrange(_REDIS_KEY, 0, limit - 1) or []
    except Exception:
        return {"items": []}
    items = []
    for raw in rows:
        try:
            items.append(json.loads(raw))
        except Exception:
            continue
    return {"items": items}
