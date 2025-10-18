from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app import main as m


def test_timeout_middleware_success_branch():
    # Ensure we enter timeout middleware with tmo>0 and succeed quickly
    client = TestClient(m.app)
    old = m.settings.request_timeout_seconds
    try:
        m.settings.request_timeout_seconds = 1.0
        r = client.get("/health")
        assert r.status_code == 200
    finally:
        m.settings.request_timeout_seconds = old



def test_jwks_cache_reuse(monkeypatch, tmp_path: Path):
    # Instrument PyJWKClient to count instantiations and verify cache reuse on 2 requests
    m.settings.jwt_enabled = True
    m.settings.jwt_jwks_url = "https://example.com/jwks.json"
    m.settings.jwt_algorithms = ["HS256"]
    prev_ttl = m.settings.jwt_cache_ttl_seconds
    # Ensure TTL is sufficiently long so back-to-back requests reuse the cached client
    m.settings.jwt_cache_ttl_seconds = 60
    # Snapshot settings and ensure cache starts empty for determinism
    snap = {
        "jwt_enabled": m.settings.jwt_enabled,
        "jwt_jwks_url": m.settings.jwt_jwks_url,
        "jwt_algorithms": list(m.settings.jwt_algorithms),
    }
    m._JWKS_CLIENT_CACHE.clear()

    class DummyClient:
        instances = 0

        def __init__(self, *args, **kwargs):
            DummyClient.instances += 1

        def get_signing_key_from_jwt(self, token):
            class K:
                key = "k"

            return K()

    # Patch jwt.PyJWKClient
    monkeypatch.setattr(m.jwt, "PyJWKClient", lambda url: DummyClient())
    token = __import__("jwt").encode({"sub": "x"}, key="k", algorithm="HS256")

    try:
        c = TestClient(m.app)
        inp = tmp_path / "in"
        out = tmp_path / "out"
        inp.mkdir(parents=True)

        # First call populates cache
        r1 = c.post(
            "/v1/latticedb/ingest",
            json={"input_dir": str(inp), "out_dir": str(out)},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r1.status_code == 200
        # Second call should reuse cached client, not instantiate a new one
        r2 = c.post(
            "/v1/latticedb/ingest",
            json={"input_dir": str(inp), "out_dir": str(out)},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r2.status_code == 200
        # Only the first call should instantiate the client; the second should reuse cache
        assert DummyClient.instances == 1
    finally:
        # restore settings
        m.settings.jwt_enabled = snap["jwt_enabled"]
        m.settings.jwt_jwks_url = snap["jwt_jwks_url"]
        m.settings.jwt_algorithms = snap["jwt_algorithms"]
        m.settings.jwt_cache_ttl_seconds = prev_ttl
        m._JWKS_CLIENT_CACHE.clear()
