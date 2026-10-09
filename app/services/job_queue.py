"""A local async job queue — MASTER BUILD PROMPT section 74.

Redis-backed (a plain LIST as the queue, LPUSH/BRPOP), with job status and
results also in Redis — intentionally simple and transparent rather than
pulling in a full task-queue framework, consistent with how the rest of
this project builds its core pieces from first principles instead of
importing them. Supports the spec's explicit requirements for background
work:

- **Idempotency** — enqueueing with the same `idempotency_key` while an
  earlier job with that key is still PENDING/RUNNING returns the existing
  `job_id` instead of creating a duplicate.
- **Retry policy** — a failed job is re-enqueued up to
  `settings.job_max_retries` times before being moved to the dead-letter
  list.
- **Dead-letter handling** — `jobs:dead_letter` holds every job_id that
  exhausted its retries, inspectable via `list_dead_letter()`.
- **Progress/failure reporting** — `get_status()` returns the job's
  current status, attempt count, and result (on success) or error (on
  failure).

Runs as an in-process background worker by default (started from
`app/api/main.py`'s lifespan via `run_forever`), not a separate OS
process — see the README's Phase 15 section for what that does and
doesn't mean for scaling this in production.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import uuid
from typing import Callable

import redis

from app.config import Settings
from app.logging_config import get_logger

logger = get_logger(__name__)

QUEUE_KEY = "jobs:queue"
DEAD_LETTER_KEY = "jobs:dead_letter"
JOB_KEY_PREFIX = "jobs:status:"
IDEMPOTENCY_KEY_PREFIX = "jobs:idempotency:"
IDEMPOTENCY_TTL_SECONDS = 24 * 3600

PENDING = "PENDING"
RUNNING = "RUNNING"
SUCCEEDED = "SUCCEEDED"
FAILED = "FAILED"

JobHandler = Callable[[dict], dict]


class JobQueueService:
    def __init__(self, settings: Settings, handlers: dict[str, JobHandler] | None = None) -> None:
        self._client: redis.Redis | None = None
        if settings.redis_url:
            try:
                self._client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
            except ValueError as exc:  # malformed URL — fail safe, not loud
                logger.warning("redis_url_invalid", error=str(exc))
                self._client = None
        self.settings = settings
        self.handlers: dict[str, JobHandler] = handlers or {}

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def register(self, job_type: str, handler: JobHandler) -> None:
        self.handlers[job_type] = handler

    def enqueue(self, job_type: str, payload: dict, idempotency_key: str | None = None) -> str:
        if self._client is None:
            raise RuntimeError("job queue is unavailable (REDIS_URL is not configured)")

        if idempotency_key:
            existing = self._client.get(f"{IDEMPOTENCY_KEY_PREFIX}{idempotency_key}")
            if existing:
                status = self.get_status(existing)
                if status and status["status"] in (PENDING, RUNNING):
                    return existing

        job_id = uuid.uuid4().hex
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        record = {
            "job_id": job_id,
            "job_type": job_type,
            "payload": payload,
            "status": PENDING,
            "attempts": 0,
            "max_retries": self.settings.job_max_retries,
            "result": None,
            "error": None,
            "idempotency_key": idempotency_key,
            "created_at": now,
            "started_at": None,
            "finished_at": None,
        }
        self._write(job_id, record)
        if idempotency_key:
            self._client.set(f"{IDEMPOTENCY_KEY_PREFIX}{idempotency_key}", job_id, ex=IDEMPOTENCY_TTL_SECONDS)
        self._client.lpush(QUEUE_KEY, job_id)
        return job_id

    def get_status(self, job_id: str) -> dict | None:
        if self._client is None:
            return None
        raw = self._client.get(f"{JOB_KEY_PREFIX}{job_id}")
        return json.loads(raw) if raw is not None else None

    def list_dead_letter(self) -> list[str]:
        if self._client is None:
            return []
        return self._client.lrange(DEAD_LETTER_KEY, 0, -1)

    def process_next(self, timeout: float = 1.0) -> bool:
        """Pops and runs one job, blocking up to `timeout` seconds for one
        to appear. Returns False if the queue was empty the whole time —
        the unit this module's own tests drive directly, since managing
        the "forever" loop's lifecycle isn't something a test should need
        to do to verify one job runs correctly."""
        if self._client is None:
            return False
        popped = self._client.brpop([QUEUE_KEY], timeout=timeout)
        if popped is None:
            return False
        _, job_id = popped
        self._run(job_id)
        return True

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        """The actual background worker, started from the FastAPI
        lifespan. The blocking BRPOP runs in a thread via `asyncio.to_thread`
        so it never stalls the event loop that's also serving requests."""
        while not stop_event.is_set():
            await asyncio.to_thread(self.process_next, self.settings.job_worker_poll_timeout_seconds)

    def _run(self, job_id: str) -> None:
        record = self.get_status(job_id)
        if record is None:
            return  # status key expired or was never written; nothing to run

        record["attempts"] += 1
        record["status"] = RUNNING
        record["started_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        self._write(job_id, record)

        handler = self.handlers.get(record["job_type"])
        try:
            if handler is None:
                raise ValueError(f"no handler registered for job_type={record['job_type']!r}")
            result = handler(record["payload"])
        except Exception as exc:
            logger.warning(
                "job_failed", job_id=job_id, job_type=record["job_type"], attempt=record["attempts"], error=str(exc)
            )
            if record["attempts"] <= record["max_retries"]:
                record["status"] = PENDING
                self._write(job_id, record)
                self._client.lpush(QUEUE_KEY, job_id)  # retry
            else:
                record["status"] = FAILED
                record["error"] = str(exc)
                record["finished_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
                self._write(job_id, record)
                self._client.lpush(DEAD_LETTER_KEY, job_id)
        else:
            record["status"] = SUCCEEDED
            record["result"] = result
            record["finished_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
            self._write(job_id, record)

    def _write(self, job_id: str, record: dict) -> None:
        self._client.set(f"{JOB_KEY_PREFIX}{job_id}", json.dumps(record))
