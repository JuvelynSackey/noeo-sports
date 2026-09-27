"""A minimal in-memory sliding-window rate limiter (Phase 12 hardening),
used to blunt credential-stuffing/brute-force attempts against
`POST /auth/token`.

This is deliberately single-process: state lives in a plain dict, not a
shared store like Redis. That's the right trade-off for the single-instance
deployment this project otherwise targets (see the Dockerfile/compose
setup), but it means the limit is per-process — running multiple API
workers (e.g. `gunicorn -w 4`) gives an attacker up to `attempts * workers`
tries, not `attempts`. A real multi-instance deployment should replace this
with a shared, distributed limiter instead of raising the numbers here to
compensate.
"""
from __future__ import annotations

import time
from collections import defaultdict


class RateLimiter:
    def __init__(self, max_attempts: int, window_seconds: float) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._attempts: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str) -> bool:
        """Records an attempt for `key` and returns whether it's allowed
        (True) or the window's limit has already been reached (False).
        Every call counts as an attempt, whether or not it's allowed — a
        caller retrying past the limit doesn't get a free extra try."""
        now = time.monotonic()
        cutoff = now - self.window_seconds
        recent = [t for t in self._attempts[key] if t > cutoff]
        recent.append(now)
        self._attempts[key] = recent
        return len(recent) <= self.max_attempts

    def reset(self, key: str) -> None:
        """Clears a key's history — called on a successful login so a
        legitimate user who mistyped their password a few times isn't left
        rate-limited afterwards."""
        self._attempts.pop(key, None)
