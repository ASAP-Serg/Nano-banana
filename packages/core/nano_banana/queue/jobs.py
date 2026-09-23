"""Redis job queue: immediate list + delayed sorted set + per-job lock."""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from typing import Any, Dict, Optional

import redis

from nano_banana.config import settings

logger = logging.getLogger(__name__)

JOBS_QUEUE = "nano_banana:jobs"
DELAYED_ZSET = "nano_banana:delayed"
LOCK_PREFIX = "nano_banana:lock:"
PROVIDER_HASH = "nano_banana:provider:moonez"

_queue: Optional["JobQueue"] = None


def _worker_id() -> str:
    return settings.WORKER_ID or os.environ.get("HOSTNAME") or uuid.uuid4().hex[:12]


class JobQueue:
    def __init__(self, url: Optional[str] = None):
        # socket_timeout > brpop timeout, иначе redis-py кидает TimeoutError вместо None
        self.client = redis.Redis.from_url(
            url or settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=30,
            health_check_interval=30,
        )
        self.worker_id = _worker_id()

    def ping(self) -> bool:
        return bool(self.client.ping())

    def enqueue(self, generation_id: int, user_id: int, request_data: dict, delay_seconds: float = 0) -> None:
        payload = json.dumps(
            {
                "generation_id": generation_id,
                "user_id": user_id,
                "request_data": request_data,
            },
            ensure_ascii=False,
        )
        if delay_seconds and delay_seconds > 0:
            self.client.zadd(DELAYED_ZSET, {payload: time.time() + delay_seconds})
            logger.info(
                "[QUEUE] delayed gen=%s in %.1fs", generation_id, delay_seconds
            )
            return
        self.client.lpush(JOBS_QUEUE, payload)
        logger.info("[QUEUE] enqueued gen=%s", generation_id)

    def _promote_delayed(self) -> None:
        now = time.time()
        ready = self.client.zrangebyscore(DELAYED_ZSET, min=0, max=now)
        if not ready:
            return
        pipe = self.client.pipeline()
        for payload in ready:
            pipe.lpush(JOBS_QUEUE, payload)
            pipe.zrem(DELAYED_ZSET, payload)
        pipe.execute()

    def pop(self, timeout: int = 5) -> Optional[Dict[str, Any]]:
        self._promote_delayed()
        try:
            item = self.client.brpop(JOBS_QUEUE, timeout=timeout)
        except (redis.TimeoutError, TimeoutError, redis.ConnectionError) as exc:
            logger.debug("[QUEUE] pop wait: %s", exc)
            return None
        if not item:
            return None
        _, raw = item
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.error("[QUEUE] bad payload: %s", raw[:200])
            return None

    def lock_key(self, generation_id: int) -> str:
        return f"{LOCK_PREFIX}{generation_id}"

    def acquire_lock(self, generation_id: int) -> bool:
        return bool(
            self.client.set(
                self.lock_key(generation_id),
                self.worker_id,
                nx=True,
                ex=settings.JOB_LOCK_TTL_SECONDS,
            )
        )

    def refresh_lock(self, generation_id: int) -> None:
        key = self.lock_key(generation_id)
        if self.client.get(key) == self.worker_id:
            self.client.expire(key, settings.JOB_LOCK_TTL_SECONDS)

    def release_lock(self, generation_id: int) -> None:
        key = self.lock_key(generation_id)
        if self.client.get(key) == self.worker_id:
            self.client.delete(key)

    def has_lock(self, generation_id: int) -> bool:
        return self.client.exists(self.lock_key(generation_id)) == 1

    def queue_size(self) -> int:
        self._promote_delayed()
        return int(self.client.llen(JOBS_QUEUE) + self.client.zcard(DELAYED_ZSET))

    def set_provider_state(self, fields: Dict[str, Any]) -> None:
        mapping = {k: "" if v is None else str(v) for k, v in fields.items()}
        if mapping:
            self.client.hset(PROVIDER_HASH, mapping=mapping)

    def get_provider_state(self) -> Dict[str, Any]:
        raw = self.client.hgetall(PROVIDER_HASH)
        return dict(raw or {})


def get_job_queue() -> JobQueue:
    global _queue
    if _queue is None:
        _queue = JobQueue()
    return _queue
