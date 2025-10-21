import asyncio
from typing import Optional

from fastapi import FastAPI
from starlette.testclient import TestClient


def test_security_headers_and_hsts(monkeypatch):
    import app.main as m
    from app.core import config as cfg

    # Enable HSTS path
    monkeypatch.setattr(cfg.settings, "enable_hsts", True, raising=False)
    client = TestClient(m.app)
    r = client.get("/v1/latticedb/models")
    assert r.status_code == 200
    # Always set
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("Referrer-Policy") == "no-referrer"
    assert r.headers.get("X-Frame-Options") == "DENY"
    # Only when enabled
    assert "Strict-Transport-Security" in r.headers


def test_request_id_generation_and_preservation():
    import app.main as m
    client = TestClient(m.app)
    # Preserved request id
    r = client.get("/v1/latticedb/models", headers={"x-request-id": "abc"})
    assert r.headers.get("X-Request-ID") == "abc"
    # Generated request id
    r2 = client.get("/v1/latticedb/models")
    rid = r2.headers.get("X-Request-ID")
    assert isinstance(rid, str) and len(rid) == 32


def test_rate_limit_in_memory_with_trusted_xff(monkeypatch):
    import app.main as m
    from app.core import config as cfg

    # Ensure clean slate for RL_STATE
    m._RL_STATE.clear()
    # Configure in-memory limiter: 1 request per window
    monkeypatch.setattr(cfg.settings, "rate_limit_enabled", True, raising=False)
    monkeypatch.setattr(cfg.settings, "rate_limit_requests", 1, raising=False)
    monkeypatch.setattr(cfg.settings, "rate_limit_period_seconds", 60, raising=False)
    monkeypatch.setattr(cfg.settings, "trust_x_forwarded_for", True, raising=False)
    # Force no Redis path
    monkeypatch.setattr(cfg.settings, "rate_limit_redis_url", "", raising=False)

    client = TestClient(m.app)
    h = {"x-forwarded-for": "1.2.3.4"}
    r1 = client.get("/v1/latticedb/models", headers=h)
    assert r1.status_code == 200
    r2 = client.get("/v1/latticedb/models", headers=h)
    assert r2.status_code == 429


def _mk_app_with_middlewares():
    # Small isolated app to exercise middleware behavior using current settings
    app = FastAPI()
    from app.core.middleware import size_limit_middleware, timeout_middleware

    app.middleware("http")(size_limit_middleware)
    app.middleware("http")(timeout_middleware)

    @app.post("/echo")
    async def echo(data: Optional[str] = None):  # type: ignore[unused-ignore]
        return {"len": len(data or "")}

    @app.get("/slow")
    async def slow(seconds: float = 0.1):
        await asyncio.sleep(seconds)
        return {"slept": seconds}

    return app


def test_size_limit_rejects_large_body(monkeypatch):
    from app.core import config as cfg
    # Set very small limit to force 413
    monkeypatch.setattr(cfg.settings, "max_request_bytes", 10, raising=False)

    app = _mk_app_with_middlewares()
    client = TestClient(app)
    body = {"data": "x" * 100}
    r = client.post("/echo", json=body)
    assert r.status_code == 413
    assert r.json().get("detail") == "request too large"


def test_timeout_middleware_returns_504(monkeypatch):
    from app.core import config as cfg
    # Very small timeout so the slow handler exceeds it
    monkeypatch.setattr(cfg.settings, "request_timeout_seconds", 0.05, raising=False)

    app = _mk_app_with_middlewares()
    client = TestClient(app)
    r = client.get("/slow", params={"seconds": 0.2})
    assert r.status_code == 504
    assert r.json().get("detail") == "request timeout"


def test_concurrency_limiter_overload_returns_503(monkeypatch):
    # Patch wait_for used inside concurrency_middleware to simulate immediate timeout on acquire
    import app.main as m
    import app.core.middleware as mw

    orig_wait_for = mw.asyncio.wait_for

    def _boom(task, timeout=0):  # noqa: ARG001
        raise asyncio.TimeoutError

    monkeypatch.setattr(mw.asyncio, "wait_for", _boom, raising=True)
    from app.core import config as cfg
    # Ensure middleware is active
    monkeypatch.setattr(cfg.settings, "max_concurrency", 1, raising=False)
    try:
        client = TestClient(m.app)
        r = client.get("/v1/latticedb/models")
        assert r.status_code == 503
        assert r.json().get("detail") == "server overloaded"
    finally:
        # ensure we restore wait_for for later tests
        monkeypatch.setattr(mw.asyncio, "wait_for", orig_wait_for, raising=True)


def test_invalid_content_length_header_is_ignored(monkeypatch):
    import app.main as m
    client = TestClient(m.app)
    r = client.get("/v1/latticedb/models", headers={"content-length": "bogus"})
    # Middleware catches ValueError and continues
    assert r.status_code == 200
