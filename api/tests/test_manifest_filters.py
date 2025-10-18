from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


def test_manifest_filters_and_sort(tmp_path):
    client = TestClient(app)

    data_dir = Path(__file__).resolve().parents[2] / "sample_data" / "docs"
    out_dir = tmp_path / "db"

    r = client.post(
        "/v1/latticedb/ingest",
        json={"input_dir": str(data_dir), "out_dir": str(out_dir)},
    )
    assert r.status_code == 200

    # Pull full manifest
    base = client.get("/v1/latticedb/manifest", params={"db_path": str(out_dir), "limit": 1000}).json()
    assert base["total"] >= 1
    items = base["items"]
    assert items

    sample = items[0]
    gid = sample["group_id"]
    lid = sample["lattice_id"]
    eh = sample["edge_hash"]

    # Filter by group_id
    resp = client.get(
        "/v1/latticedb/manifest",
        params={"db_path": str(out_dir), "group_id": gid},
    ).json()
    assert all(x["group_id"] == gid for x in resp["items"]) and resp["total"] >= 1

    # Filter by lattice_id
    resp = client.get(
        "/v1/latticedb/manifest",
        params={"db_path": str(out_dir), "lattice_id": lid},
    ).json()
    assert resp["total"] == 1 and resp["items"][0]["lattice_id"] == lid

    # Filter by edge_hash
    resp = client.get(
        "/v1/latticedb/manifest",
        params={"db_path": str(out_dir), "edge_hash": eh},
    ).json()
    assert resp["total"] >= 1 and all(x["edge_hash"] == eh for x in resp["items"]) 

    # Numeric filters and sort
    resp = client.get(
        "/v1/latticedb/manifest",
        params={
            "db_path": str(out_dir),
            "min_deltaH": 0.0,
            "max_deltaH": 10.0,
            "sort_by": "deltaH_total",
            "sort_order": "desc",
        },
    ).json()
    arr = resp["items"]
    assert all(0.0 <= float(x["deltaH_total"]) <= 10.0 for x in arr)
    # Descending check (non-strict)
    if len(arr) >= 2:
        assert float(arr[0]["deltaH_total"]) >= float(arr[-1]["deltaH_total"]) 
