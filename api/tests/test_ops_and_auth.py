from __future__ import annotations

from fastapi.testclient import TestClient
from pathlib import Path
import sys
from types import ModuleType


def test_api_key_guard_success_and_failure(tmp_path: Path):
    from app.main import app, settings

    # Require API key and set expected value
    settings.jwt_enabled = False
    settings.api_key_required = True
    settings.api_key = "sekret"

    # Prepare tiny input for protected endpoint
    inp = tmp_path / "input"
    inp.mkdir(parents=True)
    (inp / "a.txt").write_text("one two three\n")
    out = tmp_path / "db"

    c = TestClient(app)
    # Failure: missing API key
    r_fail = c.post("/v1/db/scan", json={"input_dir": str(inp), "out_dir": str(out)})
    assert r_fail.status_code == 401

    # Success with header present
    r_ok = c.post(
        "/v1/db/scan",
        headers={"X-API-Key": "sekret"},
        json={"input_dir": str(inp), "out_dir": str(out)},
    )
    assert r_ok.status_code == 200

    # Cleanup
    settings.api_key_required = False
    settings.api_key = None


def test_license_status_and_version(monkeypatch):
    from app.main import app

    c = TestClient(app)
    lr = c.get("/v1/license/status")
    assert lr.status_code == 200
    body = lr.json()
    assert set(["mode", "id", "tier", "expiry", "saas_allowed", "notice"]) <= set(body.keys())

    # Version endpoint with env-provided git sha
    monkeypatch.setenv("GIT_SHA", "abc123")
    vr = c.get("/version")
    assert vr.status_code == 200
    assert vr.json().get("git_sha") == "abc123"


def test_otel_setup_success_and_failure(monkeypatch):
    from app.main import _setup_tracing, settings

    # Build a minimal fake opentelemetry module graph
    fake_ot = ModuleType("opentelemetry")
    fake_trace = ModuleType("opentelemetry.trace")
    def set_tracer_provider(provider):  # no-op
        return None
    fake_trace.set_tracer_provider = set_tracer_provider  # type: ignore[attr-defined]

    fake_sdk = ModuleType("opentelemetry.sdk")
    fake_resources = ModuleType("opentelemetry.sdk.resources")
    fake_resources.SERVICE_NAME = "service.name"  # type: ignore[attr-defined]
    class Resource:
        @staticmethod
        def create(x):
            return object()
    fake_resources.Resource = Resource  # type: ignore[attr-defined]
    fake_trace_mod = ModuleType("opentelemetry.sdk.trace")
    class TracerProvider:
        def __init__(self, resource=None, sampler=None):
            pass
        def add_span_processor(self, sp):
            pass
    fake_trace_mod.TracerProvider = TracerProvider  # type: ignore[attr-defined]
    fake_sampling = ModuleType("opentelemetry.sdk.trace.sampling")
    class TraceIdRatioBased:
        def __init__(self, x):
            pass
    fake_sampling.TraceIdRatioBased = TraceIdRatioBased  # type: ignore[attr-defined]
    fake_export = ModuleType("opentelemetry.sdk.trace.export")
    class BatchSpanProcessor:
        def __init__(self, exporter):
            pass
    fake_export.BatchSpanProcessor = BatchSpanProcessor  # type: ignore[attr-defined]

    fake_http_export = ModuleType("opentelemetry.exporter.otlp.proto.http.trace_exporter")
    class OTLPSpanExporter:
        def __init__(self, endpoint=None):
            pass
    fake_http_export.OTLPSpanExporter = OTLPSpanExporter  # type: ignore[attr-defined]

    fake_instr = ModuleType("opentelemetry.instrumentation.fastapi")
    class FastAPIInstrumentor:
        @staticmethod
        def instrument_app(*args, **kwargs):
            return None
    fake_instr.FastAPIInstrumentor = FastAPIInstrumentor  # type: ignore[attr-defined]

    # Register modules in sys.modules
    monkeypatch.setitem(sys.modules, "opentelemetry", fake_ot)
    monkeypatch.setitem(sys.modules, "opentelemetry.trace", fake_trace)
    monkeypatch.setitem(sys.modules, "opentelemetry.sdk", fake_sdk)
    monkeypatch.setitem(sys.modules, "opentelemetry.sdk.resources", fake_resources)
    monkeypatch.setitem(sys.modules, "opentelemetry.sdk.trace", fake_trace_mod)
    monkeypatch.setitem(sys.modules, "opentelemetry.sdk.trace.export", fake_export)
    monkeypatch.setitem(sys.modules, "opentelemetry.sdk.trace.sampling", fake_sampling)
    monkeypatch.setitem(sys.modules, "opentelemetry.exporter.otlp.proto.http.trace_exporter", fake_http_export)
    monkeypatch.setitem(sys.modules, "opentelemetry.instrumentation.fastapi", fake_instr)

    settings.otel_enabled = True
    # Should not raise
    _setup_tracing()

    # Failure path: break exporter import; still should not raise
    monkeypatch.delitem(sys.modules, "opentelemetry.exporter.otlp.proto.http.trace_exporter")
    _setup_tracing()
    settings.otel_enabled = False


def test_rate_limit_trust_x_forwarded_for(monkeypatch):
    from app.main import app, settings, _RL_STATE

    settings.rate_limit_enabled = True
    settings.rate_limit_requests = 1
    settings.rate_limit_period_seconds = 60
    settings.trust_x_forwarded_for = True
    _RL_STATE.clear()

    c = TestClient(app)
    r1 = c.get("/health", headers={"x-forwarded-for": "10.0.0.1"})
    assert r1.status_code == 200
    r2 = c.get("/health", headers={"x-forwarded-for": "10.0.0.1"})
    assert r2.status_code == 429
    r3 = c.get("/health", headers={"x-forwarded-for": "10.0.0.2"})
    assert r3.status_code == 200

    # Cleanup
    settings.rate_limit_enabled = False
    settings.trust_x_forwarded_for = False
    _RL_STATE.clear()
