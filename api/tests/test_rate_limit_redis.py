from __future__ import annotations

import os
import time
import pytest
from fastapi.testclient import TestClient

from app.main import app, settings


def _redis_available(url: str) -> bool:
    try:
        import redis  # type: ignore
        r = redis.StrictRedis.from_url(url)
        r.ping()
        return True
    except Exception:
        return False


@pytest.mark.skipif(
    not _redis_available(os.environ.get("TEST_REDIS_URL", "redis://127.0.0.1:6379/15")),
    reason="Redis not available; skipping Redis rate limit test",
)
def test_redis_rate_limit_window_enforced(tmp_path):
    import redis  # type: ignore

    client = TestClient(app)
    url = os.environ.get("TEST_REDIS_URL", "redis://127.0.0.1:6379/15")

    # Save and toggle settings
    prev = {
        "enabled": settings.rate_limit_enabled,
        "requests": settings.rate_limit_requests,
        "period": settings.rate_limit_period_seconds,
        "redis_url": settings.rate_limit_redis_url,
    }
    settings.rate_limit_enabled = True
    settings.rate_limit_requests = 1
    settings.rate_limit_period_seconds = 2
    settings.rate_limit_redis_url = url

    # Isolate test DB and ensure clean window
    r = redis.StrictRedis.from_url(url)
    try:
        r.flushdb()

        # First request should pass
        resp1 = client.get("/health")
        assert resp1.status_code == 200

        # Second request in same window should hit 429
        resp2 = client.get("/health")
        assert resp2.status_code == 429

        # After period, should reset window and allow again
        time.sleep(settings.rate_limit_period_seconds)
        resp3 = client.get("/health")
        assert resp3.status_code == 200
    finally:
        # Cleanup and restore
        try:
            r.flushdb()
        except Exception:
            pass
        settings.rate_limit_enabled = prev["enabled"]
        settings.rate_limit_requests = prev["requests"]
        settings.rate_limit_period_seconds = prev["period"]
        settings.rate_limit_redis_url = prev["redis_url"]
