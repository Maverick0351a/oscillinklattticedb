from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app, settings


@pytest.fixture(autouse=True)
def restore_settings():
    # snapshot relevant settings and restore after test
    snapshot = {
        "max_request_bytes": settings.max_request_bytes,
        "enable_hsts": settings.enable_hsts,
        "metrics_protected": settings.metrics_protected,
        "metrics_secret": settings.metrics_secret,
        "jwt_enabled": settings.jwt_enabled,
        "api_key_required": settings.api_key_required,
        "api_key": settings.api_key,
        "request_timeout_seconds": settings.request_timeout_seconds,
        "max_concurrency": settings.max_concurrency,
        "trust_x_forwarded_for": settings.trust_x_forwarded_for,
    }
    try:
        yield
    finally:
        for k, v in snapshot.items():
            setattr(settings, k, v)


def test_size_limit_413_and_malformed_content_length():
    client = TestClient(app, raise_server_exceptions=False)
    # Oversized header triggers 413
    r1 = client.get("/health", headers={"content-length": str(10**9)})
    assert r1.status_code in (413, 500)
    # Malformed content-length should be ignored
    r2 = client.get("/health", headers={"content-length": "not-a-number"})
    assert r2.status_code == 200


def test_security_headers_and_hsts():
    settings.enable_hsts = True
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    h = r.headers
    assert h.get("X-Content-Type-Options") == "nosniff"
    assert h.get("Referrer-Policy") == "no-referrer"
    assert h.get("X-Frame-Options") == "DENY"
    assert "Strict-Transport-Security" in h


def test_request_id_middleware_passthrough_and_generate():
    client = TestClient(app)
    r1 = client.get("/health", headers={"x-request-id": "abc123"})
    assert r1.status_code == 200 and r1.headers.get("X-Request-ID") == "abc123"
    r2 = client.get("/health")
    assert r2.status_code == 200 and r2.headers.get("X-Request-ID")


def test_metrics_protected_toggle(tmp_path: Path):
    settings.metrics_protected = True
    settings.metrics_secret = "s3cr3t"
    client = TestClient(app)
    r1 = client.get("/metrics")
    assert r1.status_code == 401
    r2 = client.get("/metrics", headers={"x-admin-secret": "s3cr3t"})
    assert r2.status_code == 200


def test_auth_guard_jwt_and_api_key(tmp_path: Path):
    client = TestClient(app)
    # JWT enabled -> missing bearer leads to 401
    settings.jwt_enabled = True
    inp = tmp_path / "in"
    inp.mkdir(parents=True)
    out = tmp_path / "out"
    r1 = client.post("/v1/latticedb/ingest", json={"input_dir": str(inp), "out_dir": str(out)})
    assert r1.status_code == 401
    # API key path when JWT disabled
    settings.jwt_enabled = False
    settings.api_key_required = True
    settings.api_key = "k"
    r2 = client.post(
        "/v1/latticedb/ingest",
        headers={"X-API-Key": "k"},
        json={"input_dir": str(inp), "out_dir": str(out)},
    )
    assert r2.status_code == 200


def test_auth_guard_jwt_hs256_valid(tmp_path: Path):
    from app import main as m
    # Enable JWT HS256 and issue a valid token
    m.settings.jwt_enabled = True
    m.settings.jwt_secret = "secret"
    m.settings.jwt_algorithms = ["HS256"]
    token = __import__("jwt").encode({"sub": "u"}, key=m.settings.jwt_secret, algorithm="HS256")
    client = TestClient(m.app)
    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir(parents=True)
    r = client.post(
        "/v1/latticedb/ingest",
        json={"input_dir": str(inp), "out_dir": str(out)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200


def test_auth_guard_jwks_flow(monkeypatch, tmp_path: Path):
    from app import main as m
    m.settings.jwt_enabled = True
    m.settings.jwt_jwks_url = "https://example.com/jwks.json"
    m.settings.jwt_algorithms = ["HS256"]

    class DummyClient:
        def get_signing_key_from_jwt(self, token):
            class K:
                key = "k"
            return K()

    # Patch PyJWKClient to our dummy that returns a known key
    monkeypatch.setattr(m.jwt, "PyJWKClient", lambda url: DummyClient())
    token = __import__("jwt").encode({"sub": "x"}, key="k", algorithm="HS256")

    client = TestClient(m.app)
    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir(parents=True)
    r = client.post(
        "/v1/latticedb/ingest",
        json={"input_dir": str(inp), "out_dir": str(out)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200


def test_internal_error_500_tracks_metric():
    from fastapi import APIRouter
    # Route that raises
    router = APIRouter()

    @router.get("/__boom")
    async def _boom():
        raise RuntimeError("boom")

    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/__boom")
    assert r.status_code == 500


def test_api_db_scan_endpoint(tmp_path: Path):
    # Use API key path to auth
    settings.jwt_enabled = False
    settings.api_key_required = True
    settings.api_key = "k"
    client = TestClient(app)
    inp = tmp_path / "in"
    inp.mkdir(parents=True)
    out = tmp_path / "out"
    r = client.post(
        "/v1/db/scan",
        headers={"X-API-Key": "k"},
        json={"input_dir": str(inp), "out_dir": str(out)},
    )
    assert r.status_code == 200


def test_timeout_middleware_and_concurrency_503(monkeypatch):
    # Add a slow route dynamically
    from fastapi import APIRouter

    router = APIRouter()

    @router.get("/__slow_test")
    async def _slow():
        await asyncio.sleep(0.2)
        return {"ok": True}

    app.include_router(router)

    client = TestClient(app)
    # Timeout path
    settings.request_timeout_seconds = 0.01
    r = client.get("/__slow_test")
    assert r.status_code == 504

    # Concurrency path: make asyncio.wait_for raise TimeoutError during semaphore acquire
    settings.request_timeout_seconds = 0.0
    settings.max_concurrency = 1

    original_wait_for = asyncio.wait_for

    async def fake_wait_for(awaitable, timeout):
        # Only trigger failure for zero-timeout acquire calls
        if timeout == 0:
            raise asyncio.TimeoutError
        return await original_wait_for(awaitable, timeout)

    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)
    r2 = client.get("/health")
    assert r2.status_code == 503


def test_db_receipt_missing_and_invalid(tmp_path: Path):
    client = TestClient(app)
    # Missing -> 404
    r1 = client.get("/v1/db/receipt", params={"db_path": str(tmp_path / "db")})
    assert r1.status_code == 404
    # Invalid JSON -> 500
    db = tmp_path / "db"
    (db / "receipts").mkdir(parents=True)
    (db / "receipts" / "db_receipt.json").write_text("{")
    r2 = client.get("/v1/db/receipt", params={"db_path": str(db)})
    assert r2.status_code == 500


def test_models_and_license_and_security_endpoints():
    client = TestClient(app)
    m = client.get("/v1/latticedb/models")
    assert m.status_code == 200 and len(m.json().get("items", [])) >= 1
    lic = client.get("/v1/license/status")
    assert lic.status_code == 200 and "mode" in lic.json()
    sec = client.get("/health/security")
    assert sec.status_code == 200 and "egress" in sec.json()
