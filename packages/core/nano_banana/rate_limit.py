"""Redis fixed-window rate limit (shared across API workers)."""
from __future__ import annotations

import ipaddress
import logging
import time
from typing import Optional

from fastapi import HTTPException, status

from nano_banana.config import settings
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
    """Raise 429 if identifier exceeded max_attempts in the current window.

    Redis outage → 503 (fail-closed). Login/register must not proceed unbounded.
    """
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
        logger.warning("[RATE_LIMIT] redis unavailable, rejecting request: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Сервис временно недоступен. Попробуйте позже.",
        ) from exc


def _parse_single_ip(value: str) -> Optional[str]:
    raw = (value or "").strip()
    if not raw or "," in raw or " " in raw or "/" in raw:
        return None
    if raw.startswith("[") and raw.endswith("]") and ":" in raw:
        raw = raw[1:-1]
    try:
        ipaddress.ip_address(raw)
    except ValueError:
        return None
    return raw.lower()


def _parse_cidrs(raw: str) -> list:
    nets = []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            nets.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            logger.warning("[RATE_LIMIT] skip invalid trusted proxy CIDR %s", part)
    return nets


def _ip_in_cidrs(ip_text: str, networks) -> bool:
    try:
        ip = ipaddress.ip_address(ip_text)
    except ValueError:
        return False
    return any(ip in net for net in networks)


def client_ip_from_request(request, *, trust_proxy: bool = True) -> str:
    """Client IP. Trust X-Real-IP only from a peer in SECURITY_TRUSTED_PROXY_CIDRS.

    Do not use X-Forwarded-For: clients can set it. Nginx must overwrite X-Real-IP.
    """
    peer = ""
    if request.client and request.client.host:
        peer = _parse_single_ip(request.client.host) or ""

    if trust_proxy and peer:
        networks = _parse_cidrs(settings.SECURITY_TRUSTED_PROXY_CIDRS)
        if _ip_in_cidrs(peer, networks):
            forwarded = _parse_single_ip(request.headers.get("x-real-ip") or "")
            if forwarded:
                return forwarded
    return peer or "unknown"
