from __future__ import annotations
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


def test_set_display_name_and_list_and_search(tmp_path: Path):
    client = TestClient(app)

    data_dir = Path(__file__).resolve().parents[2] / "sample_data" / "docs"
    out_dir = tmp_path / "db"

    r = client.post(
        "/v1/latticedb/ingest",
        json={"input_dir": str(data_dir), "out_dir": str(out_dir)},
    )
    assert r.status_code == 200

    base = client.get("/v1/latticedb/manifest", params={"db_path": str(out_dir), "limit": 5}).json()
    assert base["total"] >= 1 and base["items"]
    lid = base["items"][0]["lattice_id"]

    # Set display name
    nm = "My Important Lattice"
    r2 = client.put(f"/v1/latticedb/lattice/{lid}/metadata", json={"db_path": str(out_dir), "display_name": nm})
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["ok"] and body["display_name"] == nm and body["lattice_id"] == lid

    # Manifest should include display_name and allow filtering/sorting
    m2 = client.get("/v1/latticedb/manifest", params={"db_path": str(out_dir), "limit": 100, "display_name": nm}).json()
    assert m2["total"] >= 1
    assert all(x.get("display_name") == nm for x in m2["items"])  # filter works

    m3 = client.get("/v1/latticedb/manifest", params={"db_path": str(out_dir), "limit": 100, "sort_by": "display_name", "sort_order": "asc"}).json()
    assert "items" in m3 and isinstance(m3["items"], list)
    # Not asserting ordering strictly; just ensure field present in items when set
    assert any(x.get("display_name") == nm for x in m3["items"])

    # Search should include display_name
    s = client.get("/v1/latticedb/search", params={"db_path": str(out_dir), "q": "important"}).json()
    assert "items" in s and isinstance(s["items"], list)
    assert any(x.get("lattice_id") == lid for x in s["items"])
