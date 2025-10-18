from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app, settings
import jwt


def _enable_jwt(secret: str = "test-secret"):
    # Toggle JWT on for the duration of a test
    prev = {
        "jwt_enabled": settings.jwt_enabled,
        "jwt_secret": settings.jwt_secret,
        "jwt_algorithms": list(settings.jwt_algorithms),
    }
    settings.jwt_enabled = True
    settings.jwt_secret = secret
    settings.jwt_algorithms = ["HS256"]
    return prev


def _restore_jwt(prev: dict):
    settings.jwt_enabled = prev["jwt_enabled"]
    settings.jwt_secret = prev["jwt_secret"]
    settings.jwt_algorithms = prev["jwt_algorithms"]


def test_ingest_requires_bearer_when_enabled(tmp_path):
    client = TestClient(app)
    prev = _enable_jwt()
    try:
        data_dir = Path(__file__).resolve().parents[2] / "sample_data" / "docs"
        out_dir = tmp_path / "db"

        # No Authorization header -> 401
        r = client.post(
            "/v1/latticedb/ingest",
            json={"input_dir": str(data_dir), "out_dir": str(out_dir)},
        )
        assert r.status_code == 401
        assert "bearer" in r.json()["detail"].lower()
    finally:
        _restore_jwt(prev)


def test_ingest_rejects_invalid_token(tmp_path):
    client = TestClient(app)
    prev = _enable_jwt()
    try:
        data_dir = Path(__file__).resolve().parents[2] / "sample_data" / "docs"
        out_dir = tmp_path / "db"

        headers = {"Authorization": "Bearer not.a.valid.token"}
        r = client.post(
            "/v1/latticedb/ingest",
            json={"input_dir": str(data_dir), "out_dir": str(out_dir)},
            headers=headers,
        )
        assert r.status_code == 401
    finally:
        _restore_jwt(prev)


def test_ingest_allows_valid_token(tmp_path):
    client = TestClient(app)
    secret = "test-secret"
    prev = _enable_jwt(secret)
    try:
        data_dir = Path(__file__).resolve().parents[2] / "sample_data" / "docs"
        out_dir = tmp_path / "db"

        token = jwt.encode({"sub": "tester"}, secret, algorithm="HS256")
        headers = {"Authorization": f"Bearer {token}"}
        r = client.post(
            "/v1/latticedb/ingest",
            json={"input_dir": str(data_dir), "out_dir": str(out_dir)},
            headers=headers,
        )
        assert r.status_code == 200
        body = r.json()
        assert "db_root" in body
    finally:
        _restore_jwt(prev)
