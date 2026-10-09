"""Redis-backed cache — MASTER BUILD PROMPT section 22.

Never the source of truth: every cached value is a TTL'd copy of
something the database can always recompute, so a Redis outage degrades to
"always recompute," never to an error. Entirely disabled (every method
becomes a no-op) when `settings.redis_url` isn't set, so local development
without Redis running behaves exactly as it did before this existed.

Invalidation is event-driven (section 22's own requirement) rather than
TTL-only where it matters: `app/api/main.py` clears the relevant keys right
after a `/sync` or `/forecast` call changes the data a cached response was
built from, instead of waiting out the TTL and serving something stale in
the meantime.
"""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

import redis

from app.config import Settings, get_settings
from app.logging_config import get_logger

logger = get_logger(__name__)


class Cache:
    def __init__(self, settings: Settings) -> None:
        self._client: redis.Redis | None = None
        if settings.redis_url:
            try:
                self._client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
            except ValueError as exc:  # malformed URL — fail safe, not loud
                logger.warning("redis_url_invalid", error=str(exc))
                self._client = None

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def get_json(self, key: str) -> Any | None:
        if self._client is None:
            return None
        try:
            raw = self._client.get(key)
        except redis.RedisError as exc:
            logger.warning("cache_get_failed", key=key, error=str(exc))
            return None
        return json.loads(raw) if raw is not None else None

    def set_json(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        if self._client is None:
            return
        try:
            self._client.set(key, json.dumps(value), ex=ttl_seconds)
        except redis.RedisError as exc:
            logger.warning("cache_set_failed", key=key, error=str(exc))

    def delete(self, key: str) -> None:
        if self._client is None:
            return
        try:
            self._client.delete(key)
        except redis.RedisError as exc:
            logger.warning("cache_delete_failed", key=key, error=str(exc))

    def delete_prefix(self, prefix: str) -> None:
        """Invalidates every key under `prefix` — used when a single event
        (a sync, a new forecast) could have changed any of several cached
        keys built from different query parameters."""
        if self._client is None:
            return
        try:
            cursor = 0
            while True:
                cursor, keys = self._client.scan(cursor=cursor, match=f"{prefix}*", count=200)
                if keys:
                    self._client.delete(*keys)
                if cursor == 0:
                    break
        except redis.RedisError as exc:
            logger.warning("cache_invalidate_failed", prefix=prefix, error=str(exc))


@lru_cache
def get_cache() -> Cache:
    return Cache(get_settings())
