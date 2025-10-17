from __future__ import annotations
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


def test_manifest_endpoint(tmp_path):
    client = TestClient(app)

    data_dir = Path(__file__).resolve().parents[2] / "sample_data" / "docs"
    out_dir = tmp_path / "db"

    r = client.post(
        "/v1/latticedb/ingest",
        json={"input_dir": str(data_dir), "out_dir": str(out_dir)},
    )
    assert r.status_code == 200

    resp = client.get("/v1/latticedb/manifest", params={"db_path": str(out_dir), "limit": 2, "offset": 0})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["total"] >= 1
    assert isinstance(payload["items"], list)
    assert len(payload["items"]) <= 2
    if payload["items"]:
        assert "lattice_id" in payload["items"][0]
