from contextlib import contextmanager

from fastapi.testclient import TestClient


@contextmanager
def _settings_snapshot(settings):
    orig = settings.model_dump()
    try:
        yield
    finally:
        for k, v in orig.items():
            setattr(settings, k, v)


def test_size_limit_middleware_handles_malformed_content_length():
    # Ensure malformed Content-Length does not crash the request
    from app.main import app

    with TestClient(app) as client:
        r = client.get("/health", headers={"content-length": "not-a-number"})
        assert r.status_code == 200
        assert r.json() == {"ok": True}


def test_rate_limit_redis_error_falls_back_to_memory_and_limits(monkeypatch):
    # Force Redis path to raise, ensure fallback to in-memory limiter triggers 429
    import sys
    import app.main as m

    class _BadRedis:
        class StrictRedis:
            @staticmethod
            def from_url(_):
                raise RuntimeError("redis unavailable")

            def pipeline(self):  # pragma: no cover - not used, but present to be safe
                raise RuntimeError("no pipeline")

    with _settings_snapshot(m.settings):
        # Inject our stub redis module so import redis succeeds but fails on from_url
        monkeypatch.setitem(sys.modules, "redis", _BadRedis)

        m.settings.rate_limit_enabled = True
        m.settings.rate_limit_requests = 1
        m.settings.rate_limit_period_seconds = 60
        m.settings.rate_limit_redis_url = "redis://example.invalid:6379/0"

        # Clear in-memory state to avoid interference
        m._RL_STATE.clear()

        with TestClient(m.app) as client:
            ok = client.get("/health")
            assert ok.status_code == 200

            # Second request in same window should be rate limited (fallback path)
            limited = client.get("/health")
            assert limited.status_code == 429
            assert limited.json().get("detail") == "rate limit exceeded"


def test_metrics_protection_blocks_without_secret_and_allows_with_secret():
    import app.main as m

    with _settings_snapshot(m.settings):
        m.settings.metrics_protected = True
        m.settings.metrics_secret = "topsecret"

        with TestClient(m.app) as client:
            r1 = client.get("/metrics")
            assert r1.status_code == 401

            r2 = client.get("/metrics", headers={"X-Admin-Secret": "topsecret"})
            assert r2.status_code == 200
            # Basic sanity: Prometheus exposition format content type
            assert "text/plain" in r2.headers.get("content-type", "")


def test_hsts_header_added_when_enabled():
    import app.main as m

    with _settings_snapshot(m.settings):
        m.settings.enable_hsts = True

        with TestClient(m.app) as client:
            r = client.get("/health")
            assert r.status_code == 200
            assert "Strict-Transport-Security" in r.headers


def test_list_models_endpoint_smoke():
    # Exercise the models listing endpoint
    from app.main import app

    with TestClient(app) as client:
        r = client.get("/v1/latticedb/models")
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body.get("items"), list)