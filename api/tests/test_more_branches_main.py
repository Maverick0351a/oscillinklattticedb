from __future__ import annotations

import importlib
from fastapi.testclient import TestClient


def test_health_security_egress_allowed(monkeypatch):
    # Ensure branch where egress is allowed is covered
    from app import main as m
    monkeypatch.setenv("LATTICEDB_EGRESS_ALLOWED", "1")
    c = TestClient(m.app)
    r = c.get("/health/security")
    assert r.status_code == 200
    assert r.json().get("egress") == "allowed"


def test_version_success_branch(monkeypatch):
    # Exercise the try-path where pkg_version resolves successfully
    from app import main as m

    def fake_pkg_version(_: str) -> str:
        return "1.2.3-test"

    monkeypatch.setattr(m, "pkg_version", fake_pkg_version)
    c = TestClient(m.app)
    r = c.get("/version")
    assert r.status_code == 200
    assert r.json().get("version") == "1.2.3-test"


def test_enable_test_only_endpoints_with_reload(monkeypatch):
    """Reload module with test endpoints enabled to cover conditional route block."""
    # Import under alias to control reload lifecycle
    import app.main as m

    # Enable via environment so Settings picks it up on reload
    monkeypatch.setenv("LATTICEDB_ENABLE_TEST_ENDPOINTS", "1")
    try:
        # Clear Prometheus default registry to avoid duplicate metric registration on reload
        from prometheus_client import REGISTRY
        for col in list(getattr(REGISTRY, "_collector_to_names").keys()):
            try:
                REGISTRY.unregister(col)
            except Exception:
                pass
        m = importlib.reload(m)
        c = TestClient(m.app)
        # Call the test-only slow endpoint (defined only when enabled)
        rr = c.get("/__test/slow", params={"seconds": 0.01})
        assert rr.status_code == 200
        assert "slept" in rr.json()
    finally:
        # Restore environment and reload back to default to avoid side effects
        monkeypatch.delenv("LATTICEDB_ENABLE_TEST_ENDPOINTS", raising=False)
        from prometheus_client import REGISTRY
        for col in list(getattr(REGISTRY, "_collector_to_names").keys()):
            try:
                REGISTRY.unregister(col)
            except Exception:
                pass
        importlib.reload(m)


def test__get_jwks_signing_key_error_branches(monkeypatch):
    import app.main as m
    # Missing URL -> raises RuntimeError
    m._JWKS_CLIENT_CACHE.clear()
    m.settings.jwt_jwks_url = None
    import pytest
    with pytest.raises(RuntimeError):
        m._get_jwks_signing_key("token")

    # Client instantiation error propagates
    m._JWKS_CLIENT_CACHE.clear()
    m.settings.jwt_jwks_url = "https://example.com/jwks.json"
    class Boom(Exception):
        pass
    def boom_client(url):
        raise Boom("nope")
    monkeypatch.setattr(m.jwt, "PyJWKClient", boom_client)
    with pytest.raises(Boom):
        m._get_jwks_signing_key("token")


def test_concurrency_release_exception_is_swallowed(monkeypatch):
    import app.main as m
    m.settings.max_concurrency = 1

    class FakeSem:
        def __init__(self, n):
            self.n = n
        async def acquire(self):
            return None
        def release(self):
            raise RuntimeError("release failed")

    # Replace asyncio.Semaphore with FakeSem just for this test
    import asyncio as aio
    monkeypatch.setattr(aio, "Semaphore", FakeSem)
    # Ensure acquire "succeeds" despite timeout=0 by overriding wait_for
    async def ok_wait_for(awaitable, timeout):
        return await awaitable
    monkeypatch.setattr(aio, "wait_for", ok_wait_for)

    try:
        c = TestClient(m.app)
        r = c.get("/health")
        # Despite release raising, middleware should swallow the error and succeed
        assert r.status_code == 200
    finally:
        # Restore concurrency settings and clear semaphore globals to avoid leakage
        m.settings.max_concurrency = 0
        m._SEM = None
        m._SEM_MAX = None
