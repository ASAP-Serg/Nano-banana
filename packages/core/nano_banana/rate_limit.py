"""Redis fixed-window rate limit (shared across API workers)."""
from __future__ import annotations

import logging
import time

from fastapi import HTTPException, status

from nano_banana.queue.jobs import get_job_queue

logger = logging.getLogger(__name__)

_PREFIX = "nano_banana:rl:"


def check_rate_limit(
    scope: str,
    identifier: str,
    max_attempts: int,
    window_seconds: int,
    detail: str = "Слишком много запросов. Попробуйте позже.",
) -> None:
    """Raise 429 if identifier exceeded max_attempts in the current window."""
    if max_attempts <= 0 or window_seconds <= 0:
        return
    bucket = int(time.time() // window_seconds)
    key = f"{_PREFIX}{scope}:{identifier}:{bucket}"
    try:
        client = get_job_queue().client
        count = int(client.incr(key))
        if count == 1:
            client.expire(key, window_seconds + 2)
        if count > max_attempts:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=detail)
    except HTTPException:
        raise
    except Exception as exc:
        # Fail open on Redis blip — better than locking everyone out.
        logger.warning("[RATE_LIMIT] redis unavailable, allowing request: %s", exc)


def client_ip_from_request(request, *, trust_proxy: bool = True) -> str:
    """Client IP. Prefer X-Real-IP from our nginx; do not trust raw XFF alone."""
    if trust_proxy:
        real_ip = (request.headers.get("x-real-ip") or "").strip()
        if real_ip:
            return real_ip.lower()
    client_host = request.client.host if request.client else None
    if client_host:
        return client_host.lower()
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded:
        return forwarded.lower()
    return "unknown"
