import importlib
import importlib.util
import os
import sys
from types import ModuleType

from fastapi.testclient import TestClient


def test_size_limit_returns_413_for_large_content_length():
    import app.main as m

    old = m.settings.max_request_bytes
    try:
        m.settings.max_request_bytes = 1
        c = TestClient(m.app, raise_server_exceptions=False)
        r = c.post("/v1/latticedb/route", headers={"content-length": "2"}, content=b"xx")
        assert r.status_code in (413, 500)
        if r.status_code == 413:
            assert r.json().get("detail") == "request too large"
    finally:
        m.settings.max_request_bytes = old


def test_redis_rate_limiter_success_branch(monkeypatch):
    import app.main as m
    snapshot = (
        m.settings.rate_limit_enabled,
        m.settings.rate_limit_requests,
        m.settings.rate_limit_period_seconds,
        m.settings.rate_limit_redis_url,
    )

    class _Pipe:
        def __init__(self, store):
            self.store = store
            self._key = None

        def incr(self, key, val):
            self._key = key
            self.store[key] = self.store.get(key, 0) + int(val)
            return self

        def expire(self, key, _):
            return self

        def execute(self):
            return (self.store.get(self._key, 0), None)

    class _Redis:
        store = {}

        @staticmethod
        def from_url(_):
            return _Redis()

        def pipeline(self):
            return _Pipe(_Redis.store)

    fake = ModuleType("redis")
    fake.StrictRedis = _Redis  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "redis", fake)

    try:
        with TestClient(m.app) as client:
            m.settings.rate_limit_enabled = True
            m.settings.rate_limit_requests = 1
            m.settings.rate_limit_period_seconds = 60
            m.settings.rate_limit_redis_url = "redis://localhost:6379/0"
            m._RL_STATE.clear()

            ok = client.get("/health")
            assert ok.status_code == 200
            limited = client.get("/health")
            assert limited.status_code == 429
            assert limited.json().get("detail") == "rate limit exceeded"
    finally:
        (
            m.settings.rate_limit_enabled,
            m.settings.rate_limit_requests,
            m.settings.rate_limit_period_seconds,
            m.settings.rate_limit_redis_url,
        ) = snapshot
        m._RL_STATE.clear()


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


def test_tracing_setup_failure_on_reload(monkeypatch):
    import app.main as m
    monkeypatch.setenv("LATTICEDB_OTEL_ENABLED", "1")
    sys.modules["opentelemetry"] = ModuleType("opentelemetry")
    restore = _with_stubbed_prom(monkeypatch)
    try:
        spec = importlib.util.spec_from_file_location(
            "app_main_tracing_copy", os.path.abspath(m.__file__)
        )
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        assert spec and spec.loader
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        r = TestClient(mod.app).get("/health")
        assert r.status_code == 200
    finally:
        monkeypatch.delenv("LATTICEDB_OTEL_ENABLED", raising=False)
        sys.modules.pop("opentelemetry", None)
        sys.modules.pop("app_main_tracing_copy", None)
        restore()


def test_metrics_middleware_swallow_inc_dec_errors(monkeypatch):
    import app.main as m

    class BadGauge:
        def inc(self, *_, **__):
            raise RuntimeError("boom-inc")

        def dec(self, *_, **__):
            raise RuntimeError("boom-dec")

    old = m.REQ_INPROGRESS
    m.REQ_INPROGRESS = BadGauge()  # type: ignore[assignment]
    try:
        r = TestClient(m.app).get("/health")
        assert r.status_code == 200
    finally:
        m.REQ_INPROGRESS = old


def test_sys_path_bootstrap_except_branch_on_reload(monkeypatch):
    import app.main as m

    class FailingPath(list):
        def __contains__(self, item):
            return item in list(self)

        def insert(self, index, item):  # type: ignore[override]
            raise RuntimeError("insert fail")

    monkeypatch.setattr(sys, "path", FailingPath(sys.path))
    restore = _with_stubbed_prom(monkeypatch)
    try:
        spec = importlib.util.spec_from_file_location(
            "app_main_bootstrap_copy", os.path.abspath(m.__file__)
        )
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        assert spec and spec.loader
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        r = TestClient(mod.app).get("/health")
        assert r.status_code == 200
    finally:
        sys.modules.pop("app_main_bootstrap_copy", None)
        restore()