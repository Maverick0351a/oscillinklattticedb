from __future__ import annotations

from fastapi.testclient import TestClient
import sys
from types import ModuleType


def test_rate_limit_redis_success(monkeypatch):
    from app.main import app, settings, _RL_STATE

    class FakePipe:
        def __init__(self):
            self.count = 0

        def incr(self, key, n):
            self.count += int(n)
            return self

        def expire(self, key, ttl):
            return self

        def execute(self):
            return (self.count, None)

    class FakeRedis:
        def pipeline(self):
            return FakePipe()

    class FakeStrict:
        @staticmethod
        def from_url(url):
            return FakeRedis()

    # Enable redis limiter and inject a fake redis module without requiring dependency
    settings.rate_limit_enabled = True
    settings.rate_limit_requests = 1
    settings.rate_limit_period_seconds = 60
    settings.rate_limit_redis_url = "redis://localhost:6379/0"
    _RL_STATE.clear()
    fake_mod = ModuleType("redis")
    fake_mod.StrictRedis = FakeStrict  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "redis", fake_mod)
    try:
        c = TestClient(app)
        r1 = c.get("/health")
        assert r1.status_code == 200
        r2 = c.get("/health")
        assert r2.status_code == 429
        # Metrics include rate-limited counter
        metrics = c.get("/metrics").text
        assert "http_rate_limited_total" in metrics
    finally:
        # cleanup
        settings.rate_limit_enabled = False
        settings.rate_limit_redis_url = None
        _RL_STATE.clear()


def test_rate_limit_redis_fallback_to_memory(monkeypatch):
    from app.main import app, settings, _RL_STATE

    class BoomStrict:
        @staticmethod
        def from_url(url):
            raise RuntimeError("redis down")

    settings.rate_limit_enabled = True
    settings.rate_limit_requests = 1
    settings.rate_limit_period_seconds = 60
    settings.rate_limit_redis_url = "redis://localhost:6379/0"
    _RL_STATE.clear()
    fake_mod = ModuleType("redis")
    fake_mod.StrictRedis = BoomStrict  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "redis", fake_mod)

    try:
        c = TestClient(app)
        r1 = c.get("/health")
        assert r1.status_code == 200
        r2 = c.get("/health")
        assert r2.status_code == 429
    finally:
        settings.rate_limit_enabled = False
        settings.rate_limit_redis_url = None
        _RL_STATE.clear()
