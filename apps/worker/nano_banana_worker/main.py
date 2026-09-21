"""Worker: Redis queue → generation providers → S3."""
from __future__ import annotations

import logging
import time

from nano_banana.generation.cleanup import cleanup_old_generations, fail_stuck_generations, reclaim_unlocked_jobs
from nano_banana.generation.processor import process_generation
from nano_banana.queue.jobs import get_job_queue
from nano_banana.storage.s3 import MinioService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("nano_banana_worker")

CLEANUP_EVERY_SECONDS = 300


def main() -> None:
    queue = get_job_queue()
    storage = MinioService()
    logger.info("[WORKER] started id=%s", queue.worker_id)
    last_maintenance = 0.0
    reclaim_unlocked_jobs()
    while True:
        now = time.time()
        if now - last_maintenance > CLEANUP_EVERY_SECONDS:
            try:
                fail_stuck_generations()
                cleanup_old_generations(storage)
                reclaim_unlocked_jobs()
            except Exception as exc:
                logger.error("[WORKER] maintenance failed: %s", exc, exc_info=True)
            last_maintenance = now
        job = queue.pop(timeout=5)
        if not job:
            continue
        generation_id = job.get("generation_id")
        user_id = job.get("user_id")
        request_data = job.get("request_data") or {}
        logger.info("[WORKER] pick gen=%s user=%s", generation_id, user_id)
        try:
            process_generation(int(generation_id), int(user_id), request_data)
        except Exception as exc:
            logger.error("[WORKER] gen=%s failed: %s", generation_id, exc, exc_info=True)


if __name__ == "__main__":
    main()
