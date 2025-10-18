from __future__ import annotations

from pathlib import Path
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app


def test_manifest_created_source_filters(tmp_path):
    client = TestClient(app)

    data_dir = Path(__file__).resolve().parents[2] / "sample_data" / "docs"
    out_dir = tmp_path / "db"

    r = client.post(
        "/v1/latticedb/ingest",
        json={"input_dir": str(data_dir), "out_dir": str(out_dir)},
    )
    assert r.status_code == 200

    # Get manifest and pick a source_file
    base = client.get("/v1/latticedb/manifest", params={"db_path": str(out_dir), "limit": 1000}).json()
    assert base["total"] >= 1
    sf = base["items"][0]["source_file"]

    # Filter by source_file
    resp = client.get(
        "/v1/latticedb/manifest",
        params={"db_path": str(out_dir), "source_file": sf},
    ).json()
    assert resp["total"] >= 1 and all(x["source_file"] == sf for x in resp["items"]) 

    # Time-window filters
    now = datetime.now(timezone.utc)
    earlier = (now - timedelta(days=1)).isoformat()
    later = (now + timedelta(days=1)).isoformat()

    resp = client.get(
        "/v1/latticedb/manifest",
        params={"db_path": str(out_dir), "created_from": earlier},
    )
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1

    resp = client.get(
        "/v1/latticedb/manifest",
        params={"db_path": str(out_dir), "created_to": later},
    )
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1
