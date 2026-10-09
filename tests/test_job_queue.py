import fakeredis
import pytest

from app.config import Settings
from app.services.job_queue import FAILED, PENDING, SUCCEEDED, JobQueueService


@pytest.fixture()
def queue(monkeypatch):
    monkeypatch.setattr(
        "redis.Redis.from_url", classmethod(lambda cls, *a, **k: fakeredis.FakeRedis(decode_responses=True))
    )
    return JobQueueService(Settings(redis_url="redis://localhost:6379/0", job_max_retries=1))


def test_disabled_without_redis_url():
    q = JobQueueService(Settings(redis_url=None))
    assert not q.enabled
    assert q.get_status("nope") is None
    assert q.list_dead_letter() == []
    assert q.process_next(timeout=0.01) is False
    with pytest.raises(RuntimeError):
        q.enqueue("full_sync", {})


def test_enqueue_sets_pending_status(queue):
    job_id = queue.enqueue("echo", {"value": 42})
    status = queue.get_status(job_id)
    assert status["status"] == PENDING
    assert status["job_type"] == "echo"
    assert status["payload"] == {"value": 42}
    assert status["attempts"] == 0


def test_process_next_runs_a_registered_handler_and_succeeds(queue):
    queue.register("echo", lambda payload: {"echoed": payload["value"]})
    job_id = queue.enqueue("echo", {"value": 7})

    processed = queue.process_next(timeout=0.1)

    assert processed is True
    status = queue.get_status(job_id)
    assert status["status"] == SUCCEEDED
    assert status["result"] == {"echoed": 7}
    assert status["attempts"] == 1
    assert status["started_at"] is not None
    assert status["finished_at"] is not None


def test_process_next_returns_false_when_queue_is_empty(queue):
    assert queue.process_next(timeout=0.05) is False


def test_missing_handler_fails_the_job(queue):
    job_id = queue.enqueue("unregistered_type", {})
    queue.process_next(timeout=0.1)
    queue.process_next(timeout=0.1)  # consume the retry too

    status = queue.get_status(job_id)
    assert status["status"] == FAILED
    assert "no handler registered" in status["error"]


def test_failed_job_retries_up_to_max_retries_then_moves_to_dead_letter(queue):
    attempts = []

    def _always_fails(payload):
        attempts.append(1)
        raise ValueError("boom")

    queue.register("flaky", _always_fails)
    job_id = queue.enqueue("flaky", {})

    # job_max_retries=1 -> first attempt fails and retries, second attempt
    # fails and goes to dead-letter: two process_next calls total.
    assert queue.process_next(timeout=0.1) is True
    status_after_first = queue.get_status(job_id)
    assert status_after_first["status"] == PENDING  # re-queued for retry
    assert status_after_first["attempts"] == 1

    assert queue.process_next(timeout=0.1) is True
    status_after_second = queue.get_status(job_id)
    assert status_after_second["status"] == FAILED
    assert status_after_second["attempts"] == 2
    assert "boom" in status_after_second["error"]

    assert len(attempts) == 2
    assert job_id in queue.list_dead_letter()


def test_a_job_that_succeeds_on_retry_is_not_dead_lettered(queue):
    calls = {"n": 0}

    def _fails_once(payload):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("transient")
        return {"ok": True}

    queue.register("retry_then_ok", _fails_once)
    job_id = queue.enqueue("retry_then_ok", {})

    queue.process_next(timeout=0.1)  # fails, re-queued
    assert queue.get_status(job_id)["status"] == PENDING

    queue.process_next(timeout=0.1)  # succeeds this time
    status = queue.get_status(job_id)
    assert status["status"] == SUCCEEDED
    assert status["result"] == {"ok": True}
    assert job_id not in queue.list_dead_letter()


def test_idempotency_key_returns_the_same_job_while_pending(queue):
    job_id_1 = queue.enqueue("echo", {"value": 1}, idempotency_key="same-key")
    job_id_2 = queue.enqueue("echo", {"value": 2}, idempotency_key="same-key")

    assert job_id_1 == job_id_2
    # Only one job was actually queued, not two.
    assert queue.get_status(job_id_1)["payload"] == {"value": 1}


def test_idempotency_key_allows_a_new_job_once_the_previous_one_finished(queue):
    queue.register("echo", lambda payload: {"echoed": payload["value"]})
    job_id_1 = queue.enqueue("echo", {"value": 1}, idempotency_key="same-key")
    queue.process_next(timeout=0.1)
    assert queue.get_status(job_id_1)["status"] == SUCCEEDED

    job_id_2 = queue.enqueue("echo", {"value": 2}, idempotency_key="same-key")
    assert job_id_2 != job_id_1


def test_get_status_for_unknown_job_is_none(queue):
    assert queue.get_status("does-not-exist") is None
