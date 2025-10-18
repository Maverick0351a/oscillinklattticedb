from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from types import ModuleType
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


def _with_stubbed_prom(monkeypatch):
    orig_prom = sys.modules.get("prometheus_client")
    orig_prom_metrics = sys.modules.get("prometheus_client.metrics")
    orig_prom_registry = sys.modules.get("prometheus_client.registry")

    stub = ModuleType("prometheus_client")

    class _Noop:
        def __init__(self, *a, **k):
            pass

        def labels(self, *a, **k):
            return self

        def inc(self, *a, **k):
            pass

        def dec(self, *a, **k):
            pass

        def observe(self, *a, **k):
            pass

        def set(self, *a, **k):
            pass

    stub.Counter = _Noop  # type: ignore[attr-defined]
    stub.Histogram = _Noop  # type: ignore[attr-defined]
    stub.Gauge = _Noop  # type: ignore[attr-defined]

    def _gen():
        return b""

    stub.generate_latest = _gen  # type: ignore[attr-defined]
    stub.CONTENT_TYPE_LATEST = "text/plain"  # type: ignore[attr-defined]

    sys.modules["prometheus_client"] = stub
    sys.modules["prometheus_client.metrics"] = ModuleType("prometheus_client.metrics")
    reg = ModuleType("prometheus_client.registry")
    reg.REGISTRY = object()  # type: ignore[attr-defined]
    sys.modules["prometheus_client.registry"] = reg

    def _restore():
        if orig_prom is not None:
            sys.modules["prometheus_client"] = orig_prom
        else:
            sys.modules.pop("prometheus_client", None)
        if orig_prom_metrics is not None:
            sys.modules["prometheus_client.metrics"] = orig_prom_metrics
        else:
            sys.modules.pop("prometheus_client.metrics", None)
        if orig_prom_registry is not None:
            sys.modules["prometheus_client.registry"] = orig_prom_registry
        else:
            sys.modules.pop("prometheus_client.registry", None)

    return _restore


def test_enable_test_only_endpoints_with_reload(monkeypatch):
    """Import a fresh copy with test endpoints enabled to cover conditional route block without mutating the canonical module."""
    import app.main as m

    # Enable via environment so Settings picks it up on fresh import
    monkeypatch.setenv("LATTICEDB_ENABLE_TEST_ENDPOINTS", "1")
    restore = _with_stubbed_prom(monkeypatch)
    try:
        # Load a separate copy under an alias to avoid replacing sys.modules['app.main']
        spec = importlib.util.spec_from_file_location("app_main_test_endpoints_copy", os.path.abspath(m.__file__))
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        assert spec and spec.loader
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        c = TestClient(mod.app)
        # Call the test-only slow endpoint (defined only when enabled)
        rr = c.get("/__test/slow", params={"seconds": 0.01})
        assert rr.status_code == 200
        assert "slept" in rr.json()
    finally:
        # Restore environment and drop the alias module
        monkeypatch.delenv("LATTICEDB_ENABLE_TEST_ENDPOINTS", raising=False)
        sys.modules.pop("app_main_test_endpoints_copy", None)
        restore()


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
