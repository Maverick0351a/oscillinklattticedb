from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


def test_search_endpoint(tmp_path):
    client = TestClient(app)

    data_dir = Path(__file__).resolve().parents[2] / "sample_data" / "docs"
    out_dir = tmp_path / "db"

    r = client.post(
        "/v1/latticedb/ingest",
        json={"input_dir": str(data_dir), "out_dir": str(out_dir)},
    )
    assert r.status_code == 200

    # Search by substring in source_file or lattice_id
    resp = client.get("/v1/latticedb/search", params={"db_path": str(out_dir), "q": "doc"})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["total"] >= 1
    assert any("doc" in x.get("source_file", "").lower() or "l-" in x.get("lattice_id"," ").lower() for x in payload["items"]) 
