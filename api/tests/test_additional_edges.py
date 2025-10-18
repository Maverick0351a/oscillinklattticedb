from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app import main as m


def test_manifest_limit_clamp_and_negative_limit(tmp_path: Path):
    c = TestClient(m.app)
    data_dir = Path(__file__).resolve().parents[2] / "sample_data" / "docs"
    out = tmp_path / "db"
    r = c.post("/v1/latticedb/ingest", json={"input_dir": str(data_dir), "out_dir": str(out)})
    assert r.status_code == 200

    # Very large limit should clamp to <= 500
    big = c.get("/v1/latticedb/manifest", params={"db_path": str(out), "limit": 10000}).json()
    assert 0 <= len(big["items"]) <= 500

    # Negative limit yields empty slice
    neg = c.get("/v1/latticedb/manifest", params={"db_path": str(out), "limit": -1}).json()
    assert len(neg["items"]) == 0


def test_search_limit_clamp_and_offset(tmp_path: Path):
    c = TestClient(m.app)
    data_dir = Path(__file__).resolve().parents[2] / "sample_data" / "docs"
    out = tmp_path / "db"
    r = c.post("/v1/latticedb/ingest", json={"input_dir": str(data_dir), "out_dir": str(out)})
    assert r.status_code == 200

    all_items = c.get("/v1/latticedb/search", params={"db_path": str(out), "q": "", "limit": 1000}).json()["items"]
    # Clamp behavior
    big = c.get("/v1/latticedb/search", params={"db_path": str(out), "q": "", "limit": 10000}).json()["items"]
    assert 0 <= len(big) <= 500
    # Negative limit -> empty
    empty = c.get("/v1/latticedb/search", params={"db_path": str(out), "q": "", "limit": -5}).json()["items"]
    assert len(empty) == 0
    # Offset beyond total -> empty
    off = c.get("/v1/latticedb/search", params={"db_path": str(out), "q": "", "limit": 10, "offset": len(all_items)+10}).json()["items"]
    assert len(off) == 0


def test_jwt_missing_secret_returns_401(tmp_path: Path):
    # Enable JWT without a secret or jwks url -> guard raises internally and returns 401
    snap = {
        "jwt_enabled": m.settings.jwt_enabled,
        "jwt_secret": m.settings.jwt_secret,
        "jwt_jwks_url": m.settings.jwt_jwks_url,
        "jwt_algorithms": list(m.settings.jwt_algorithms),
    }
    try:
        m.settings.jwt_enabled = True
        m.settings.jwt_secret = None
        m.settings.jwt_jwks_url = None
        m.settings.jwt_algorithms = ["HS256"]

        c = TestClient(m.app)
        inp = tmp_path / "in"
        out = tmp_path / "out"
        inp.mkdir(parents=True)
        # Any bearer token will do; secret is missing so path should error and translate to 401
        r = c.post(
            "/v1/latticedb/ingest",
            json={"input_dir": str(inp), "out_dir": str(out)},
            headers={"Authorization": "Bearer whatever"},
        )
        assert r.status_code == 401
    finally:
        m.settings.jwt_enabled = snap["jwt_enabled"]
        m.settings.jwt_secret = snap["jwt_secret"]
        m.settings.jwt_jwks_url = snap["jwt_jwks_url"]
        m.settings.jwt_algorithms = snap["jwt_algorithms"]
