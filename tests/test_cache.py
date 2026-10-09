import fakeredis
import pytest

from app.config import Settings
from app.services.cache import Cache


@pytest.fixture()
def cache(monkeypatch):
    monkeypatch.setattr(
        "redis.Redis.from_url", classmethod(lambda cls, *a, **k: fakeredis.FakeRedis(decode_responses=True))
    )
    return Cache(Settings(redis_url="redis://localhost:6379/0"))


def test_disabled_without_redis_url():
    cache = Cache(Settings(redis_url=None))
    assert not cache.enabled
    assert cache.get_json("k") is None
    cache.set_json("k", {"a": 1})  # no-op, must not raise
    cache.delete("k")  # no-op, must not raise
    cache.delete_prefix("k")  # no-op, must not raise


def test_set_and_get_round_trips_json(cache):
    assert cache.enabled
    cache.set_json("comp:list", {"competitions": ["a", "b"]})
    assert cache.get_json("comp:list") == {"competitions": ["a", "b"]}


def test_get_missing_key_returns_none(cache):
    assert cache.get_json("does-not-exist") is None


def test_delete_removes_a_key(cache):
    cache.set_json("k", {"v": 1})
    cache.delete("k")
    assert cache.get_json("k") is None


def test_delete_prefix_removes_every_matching_key(cache):
    cache.set_json("fixtures:compA:season1", {"x": 1})
    cache.set_json("fixtures:compA:season2", {"x": 2})
    cache.set_json("fixtures:compB:season1", {"x": 3})

    cache.delete_prefix("fixtures:compA")

    assert cache.get_json("fixtures:compA:season1") is None
    assert cache.get_json("fixtures:compA:season2") is None
    assert cache.get_json("fixtures:compB:season1") == {"x": 3}


def test_ttl_is_applied(cache):
    cache.set_json("k", {"v": 1}, ttl_seconds=60)
    ttl = cache._client.ttl("k")
    assert 0 < ttl <= 60


def test_redis_errors_degrade_to_none_rather_than_raising(cache, monkeypatch):
    def _boom(*a, **k):
        import redis
        raise redis.RedisError("simulated outage")

    monkeypatch.setattr(cache._client, "get", _boom)
    assert cache.get_json("k") is None

    monkeypatch.setattr(cache._client, "set", _boom)
    cache.set_json("k", {"v": 1})  # must not raise
