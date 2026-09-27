from app.services.rate_limiter import RateLimiter


def test_allows_attempts_up_to_the_limit():
    limiter = RateLimiter(max_attempts=3, window_seconds=60)
    assert limiter.check("k") is True
    assert limiter.check("k") is True
    assert limiter.check("k") is True


def test_blocks_once_the_limit_is_exceeded():
    limiter = RateLimiter(max_attempts=3, window_seconds=60)
    for _ in range(3):
        limiter.check("k")
    assert limiter.check("k") is False


def test_keys_are_independent():
    limiter = RateLimiter(max_attempts=1, window_seconds=60)
    assert limiter.check("a") is True
    assert limiter.check("b") is True
    assert limiter.check("a") is False
    assert limiter.check("b") is False


def test_old_attempts_fall_out_of_the_window(monkeypatch):
    limiter = RateLimiter(max_attempts=1, window_seconds=10)
    times = iter([100.0, 111.0])  # 11s apart, outside the 10s window
    monkeypatch.setattr("app.services.rate_limiter.time.monotonic", lambda: next(times))

    assert limiter.check("k") is True
    assert limiter.check("k") is True  # the first attempt has expired out of the window


def test_reset_clears_history():
    limiter = RateLimiter(max_attempts=1, window_seconds=60)
    limiter.check("k")
    assert limiter.check("k") is False

    limiter.reset("k")
    assert limiter.check("k") is True
