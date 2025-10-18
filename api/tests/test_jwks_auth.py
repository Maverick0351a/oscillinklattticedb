from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app, settings, _JWKS_CLIENT_CACHE
import jwt


class _FakeSigningKey:
    def __init__(self, key: str):
        self.key = key


class _FakePyJWKClient:
    def __init__(self, url: str):
        self.url = url

    def get_signing_key_from_jwt(self, token: str):
        # Always return a signing key for our tests; the token is validated later by PyJWT
        return _FakeSigningKey("secret")


def _enable_jwks():
    prev = {
        "jwt_enabled": settings.jwt_enabled,
        "jwt_secret": settings.jwt_secret,
        "jwt_algorithms": list(settings.jwt_algorithms),
        "jwt_jwks_url": settings.jwt_jwks_url,
        "jwt_leeway": settings.jwt_leeway,
        "jwt_cache_ttl_seconds": settings.jwt_cache_ttl_seconds,
    }
    settings.jwt_enabled = True
    settings.jwt_secret = None
    settings.jwt_algorithms = ["HS256"]  # using HS in tests with a fake JWKS client
    settings.jwt_jwks_url = "https://example.test/jwks.json"
    settings.jwt_leeway = 0
    settings.jwt_cache_ttl_seconds = 300
    # Clear JWKS cache to avoid state bleed
    _JWKS_CLIENT_CACHE.clear()
    return prev


def _restore(prev: dict):
    settings.jwt_enabled = prev["jwt_enabled"]
    settings.jwt_secret = prev["jwt_secret"]
    settings.jwt_algorithms = prev["jwt_algorithms"]
    settings.jwt_jwks_url = prev["jwt_jwks_url"]
    settings.jwt_leeway = prev["jwt_leeway"]
    settings.jwt_cache_ttl_seconds = prev["jwt_cache_ttl_seconds"]
    _JWKS_CLIENT_CACHE.clear()


def test_jwks_allows_valid_token(monkeypatch, tmp_path):
    client = TestClient(app)
    prev = _enable_jwks()
    try:
        # Monkeypatch the PyJWKClient to our fake
        monkeypatch.setattr(jwt, "PyJWKClient", _FakePyJWKClient)

        data_dir = Path(__file__).resolve().parents[2] / "sample_data" / "docs"
        out_dir = tmp_path / "db"

        token = jwt.encode({"sub": "tester"}, "secret", algorithm="HS256")
        headers = {"Authorization": f"Bearer {token}"}
        r = client.post(
            "/v1/latticedb/ingest",
            json={"input_dir": str(data_dir), "out_dir": str(out_dir)},
            headers=headers,
        )
        assert r.status_code == 200
        assert "db_root" in r.json()
    finally:
        _restore(prev)


def test_jwks_rejects_invalid_token(monkeypatch, tmp_path):
    client = TestClient(app)
    prev = _enable_jwks()
    try:
        monkeypatch.setattr(jwt, "PyJWKClient", _FakePyJWKClient)

        data_dir = Path(__file__).resolve().parents[2] / "sample_data" / "docs"
        out_dir = tmp_path / "db"

        # Token signed with the wrong secret should fail verification
        token = jwt.encode({"sub": "tester"}, "wrong", algorithm="HS256")
        headers = {"Authorization": f"Bearer {token}"}
        r = client.post(
            "/v1/latticedb/ingest",
            json={"input_dir": str(data_dir), "out_dir": str(out_dir)},
            headers=headers,
        )
        assert r.status_code == 401
    finally:
        _restore(prev)
