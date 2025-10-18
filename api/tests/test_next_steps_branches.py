from __future__ import annotations
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main as m


@pytest.fixture(autouse=True)
def restore_settings_autouse():
    snap = {
        "embed_strict_hash": m.settings.embed_strict_hash,
        "jwt_enabled": m.settings.jwt_enabled,
        "api_key_required": m.settings.api_key_required,
        "api_key": m.settings.api_key,
        "metrics_protected": m.settings.metrics_protected,
        "metrics_secret": m.settings.metrics_secret,
        "license_mode": m.settings.license_mode,
        # rate limit related
        "rate_limit_enabled": m.settings.rate_limit_enabled,
        "rate_limit_requests": m.settings.rate_limit_requests,
        "rate_limit_period_seconds": m.settings.rate_limit_period_seconds,
        "trust_x_forwarded_for": m.settings.trust_x_forwarded_for,
        "rate_limit_redis_url": m.settings.rate_limit_redis_url,
    }
    try:
        yield
    finally:
        for k, v in snap.items():
            setattr(m.settings, k, v)


def test_route_strict_hash_raises_500():
    # When strict hash is enabled, embedding backend raises -> FastAPI returns 500
    m.settings.embed_strict_hash = True
    client = TestClient(m.app, raise_server_exceptions=False)
    r = client.post("/v1/latticedb/route", json={"q": "hello", "k_lattices": 1})
    assert r.status_code == 500


def test_compose_qmeta_strict_hash_fallback(tmp_path: Path):
    client = TestClient(m.app)

    # Ingest a tiny dataset into a temp DB
    data_dir = Path(__file__).resolve().parents[2] / "sample_data" / "docs"
    out_dir = tmp_path / "db"
    r_ing = client.post(
        "/v1/latticedb/ingest",
        json={"input_dir": str(data_dir), "out_dir": str(out_dir)},
    )
    assert r_ing.status_code == 200
    db_root = r_ing.json()["db_root"]

    # Route to get candidate lattice IDs (keep strict_hash disabled for route)
    r_route = client.post(
        "/v1/latticedb/route",
        json={"db_path": str(out_dir), "q": "What is Oscillink?", "k_lattices": 3},
    )
    assert r_route.status_code == 200
    cands = r_route.json().get("candidates", [])
    assert cands
    lattice_ids = [c["lattice_id"] for c in cands][:2]

    # Enable strict hash only for compose's q_meta load path; it should fallback (no crash)
    m.settings.embed_strict_hash = True
    r_comp = client.post(
        "/v1/latticedb/compose",
        json={
            "db_path": str(out_dir),
            "q": "What is Oscillink?",
            "lattice_ids": lattice_ids,
        },
    )
    assert r_comp.status_code == 200
    ctx = r_comp.json().get("context_pack", {})
    comp = ctx.get("receipts", {}).get("composite", {})
    # Fallback path uses stub model sha when q_meta load fails under strict-hash
    assert comp.get("model_sha256") == "stub-model-sha256"
    assert comp.get("db_root") == db_root


def test_license_status_notice_toggle():
    client = TestClient(m.app)

    m.settings.license_mode = "dev"
    r1 = client.get("/v1/license/status")
    assert r1.status_code == 200
    assert r1.json().get("notice") == "Not for production use"

    m.settings.license_mode = "prod"
    r2 = client.get("/v1/license/status")
    assert r2.status_code == 200
    assert r2.json().get("notice") == "Production license active"


def test_db_receipt_endpoint_success(tmp_path: Path):
    client = TestClient(m.app)

    data_dir = Path(__file__).resolve().parents[2] / "sample_data" / "docs"
    out_dir = tmp_path / "db"
    r_ing = client.post(
        "/v1/latticedb/ingest",
        json={"input_dir": str(data_dir), "out_dir": str(out_dir)},
    )
    assert r_ing.status_code == 200
    db_root_ing = r_ing.json()["db_root"]

    r_db = client.get("/v1/db/receipt", params={"db_path": str(out_dir)})
    assert r_db.status_code == 200
    dbj = r_db.json()
    assert dbj.get("db_root") == db_root_ing


def test_jwks_invalid_token_returns_401(monkeypatch, tmp_path: Path):
    # Configure JWKS flow but return a wrong signing key so jwt.decode fails
    m.settings.jwt_enabled = True
    m.settings.jwt_jwks_url = "https://example.com/jwks.json"
    m.settings.jwt_algorithms = ["HS256"]
    # Ensure cache is clear so our dummy client is used
    m._JWKS_CLIENT_CACHE.clear()

    class DummyClientWrong:
        def get_signing_key_from_jwt(self, token):
            class K:
                key = "wrong-key"
            return K()

    monkeypatch.setattr(m.jwt, "PyJWKClient", lambda url: DummyClientWrong())
    # Token is signed with 'k' but JWKS returns 'wrong-key' -> decode should fail
    token = __import__("jwt").encode({"sub": "x"}, key="k", algorithm="HS256")

    c = TestClient(m.app)
    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir(parents=True)
    r = c.post(
        "/v1/latticedb/ingest",
        json={"input_dir": str(inp), "out_dir": str(out)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 401


def test_concurrency_semaphore_reinit_branch(monkeypatch):
    # Exercise branch where _SEM_MAX != max_c triggers re-initialization (both requests should succeed)
    m.settings.max_concurrency = 2
    # Avoid flakiness from zero-timeout acquire by giving a tiny timeout instead
    import asyncio as _asyncio
    original_wait_for = _asyncio.wait_for
    async def _wf(awaitable, timeout):
        if timeout == 0:
            return await original_wait_for(awaitable, 0.05)
        return await original_wait_for(awaitable, timeout)
    monkeypatch.setattr(_asyncio, "wait_for", _wf)
    c = TestClient(m.app)
    r1 = c.get("/health")
    assert r1.status_code == 200
    # Change setting to force new semaphore creation
    m.settings.max_concurrency = 3
    r2 = c.get("/health")
    assert r2.status_code == 200
    # Cleanup
    m.settings.max_concurrency = 0


def test_compose_gating_returns_empty_working_set(tmp_path: Path):
    client = TestClient(m.app)
    data_dir = Path(__file__).resolve().parents[2] / "sample_data" / "docs"
    out_dir = tmp_path / "db"
    r_ing = client.post(
        "/v1/latticedb/ingest",
        json={"input_dir": str(data_dir), "out_dir": str(out_dir)},
    )
    assert r_ing.status_code == 200
    # Route to get a few candidate lattice IDs
    r_route = client.post(
        "/v1/latticedb/route",
        json={"db_path": str(out_dir), "q": "q", "k_lattices": 3},
    )
    assert r_route.status_code == 200
    sel = [c["lattice_id"] for c in r_route.json().get("candidates", [])][:2]
    # Force gating failure with impossible thresholds
    r_comp = client.post(
        "/v1/latticedb/compose",
        json={
            "db_path": str(out_dir),
            "q": "q",
            "lattice_ids": sel,
            "epsilon": 0.0,
            "tau": 10.0,
        },
    )
    assert r_comp.status_code == 200
    cp = r_comp.json().get("context_pack", {})
    assert cp.get("working_set") == []


def test_metrics_middleware_exception_fallback_sets_500(monkeypatch):
    # Create a route that raises and use TestClient with raise_server_exceptions=True to propagate
    # so metrics_middleware sees response=None and uses fallback 500 path.
    from fastapi import APIRouter

    router = APIRouter()

    @router.get("/__boom_fallback")
    async def _boom_fallback():
        raise RuntimeError("boom2")

    m.app.include_router(router)

    # Default TestClient raises exceptions; we catch and then check metrics text
    c = TestClient(m.app)  # raise_server_exceptions=True (default)
    with pytest.raises(Exception):
        c.get("/__boom_fallback")
    # Metrics should still have error counters for that path, and middleware should not crash
    metrics = TestClient(m.app, raise_server_exceptions=False).get("/metrics").text
    assert "http_requests_errors_total" in metrics
    assert "/__boom_fallback" in metrics


def test_jwks_cache_expiry_reinstantiates_client(monkeypatch, tmp_path: Path):
    # Verify that after TTL the JWKS client is recreated (instances increments to 2)
    m.settings.jwt_enabled = True
    m.settings.jwt_jwks_url = "https://example.com/jwks.json"
    m.settings.jwt_algorithms = ["HS256"]
    m.settings.jwt_cache_ttl_seconds = 1
    m._JWKS_CLIENT_CACHE.clear()

    base = 1_000_000.0
    # Monkeypatch time on the app.main module where it's referenced
    monkeypatch.setattr(m.time, "time", lambda: base)

    class DummyClientCount:
        instances = 0

        def __init__(self, *args, **kwargs):
            DummyClientCount.instances += 1

        def get_signing_key_from_jwt(self, token):
            class K:
                key = "k"
            return K()

    monkeypatch.setattr(m.jwt, "PyJWKClient", lambda url: DummyClientCount())
    token = __import__("jwt").encode({"sub": "x"}, key="k", algorithm="HS256")

    c = TestClient(m.app)
    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir(parents=True)
    r1 = c.post(
        "/v1/latticedb/ingest",
        json={"input_dir": str(inp), "out_dir": str(out)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r1.status_code == 200
    # Advance time beyond TTL to force re-instantiation
    monkeypatch.setattr(m.time, "time", lambda: base + 5)
    r2 = c.post(
        "/v1/latticedb/ingest",
        json={"input_dir": str(inp), "out_dir": str(out)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r2.status_code == 200
    assert DummyClientCount.instances == 2


def test_rate_limit_unknown_client_path(monkeypatch):
    # Call the rate_limit_middleware directly with a Request lacking 'client' scope to keep client='unknown'
    from starlette.requests import Request as SRequest
    from fastapi.responses import JSONResponse
    from app.main import rate_limit_middleware, _RL_STATE

    m.settings.rate_limit_enabled = True
    m.settings.rate_limit_requests = 1
    m.settings.rate_limit_period_seconds = 60
    m.settings.trust_x_forwarded_for = False
    _RL_STATE.clear()

    async def call_next_ok(_req):
        return JSONResponse({"ok": True})

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/__rl_test",
        "headers": [],
        # No 'client' key -> Request.client is None
    }
    req = SRequest(scope)

    # First call allowed
    resp1 = m.asyncio.get_event_loop().run_until_complete(rate_limit_middleware(req, call_next_ok))
    assert resp1.status_code == 200
    # Second call in same window should be 429
    resp2 = m.asyncio.get_event_loop().run_until_complete(rate_limit_middleware(req, call_next_ok))
    assert resp2.status_code == 429
    # Cleanup
    _RL_STATE.clear()
