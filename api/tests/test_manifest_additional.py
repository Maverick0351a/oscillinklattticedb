from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


def test_manifest_sort_deltaH_asc_default_order(tmp_path: Path):
    client = TestClient(app)
    data_dir = Path(__file__).resolve().parents[2] / "sample_data" / "docs"
    out_dir = tmp_path / "db"
    r = client.post("/v1/latticedb/ingest", json={"input_dir": str(data_dir), "out_dir": str(out_dir)})
    assert r.status_code == 200

    # Omit sort_order (defaults to asc) and ensure ascending by deltaH_total
    resp = client.get(
        "/v1/latticedb/manifest",
        params={"db_path": str(out_dir), "sort_by": "deltaH_total"},
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    if len(items) >= 2:
        vals = [float(i.get("deltaH_total", 0.0)) for i in items]
        assert vals == sorted(vals)


def test_manifest_time_window_accepts_Z_suffix_and_ordering(tmp_path: Path):
    client = TestClient(app)
    data_dir = Path(__file__).resolve().parents[2] / "sample_data" / "docs"
    out_dir = tmp_path / "db"
    r = client.post("/v1/latticedb/ingest", json={"input_dir": str(data_dir), "out_dir": str(out_dir)})
    assert r.status_code == 200

    now = datetime.now(timezone.utc)
    earlier_Z = (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    later_Z = (now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    # Window with Z-suffixed timestamps should include current items
    ok = client.get(
        "/v1/latticedb/manifest",
        params={"db_path": str(out_dir), "created_from": earlier_Z, "created_to": later_Z},
    ).json()
    assert ok["total"] >= 1

    # Inverted window (from after to before) should reasonably yield zero
    inv = client.get(
        "/v1/latticedb/manifest",
        params={"db_path": str(out_dir), "created_from": later_Z, "created_to": earlier_Z},
    ).json()
    # Depending on timestamps granularity, allow zero or very small count, but pagination slice may be empty
    if ok["total"] >= 1:
        assert len(inv["items"]) == 0


def test_readyz_router_meta_unreadable_reports_false(tmp_path: Path):
    client = TestClient(app)
    data_dir = Path(__file__).resolve().parents[2] / "sample_data" / "docs"
    out_dir = tmp_path / "db"
    r = client.post("/v1/latticedb/ingest", json={"input_dir": str(data_dir), "out_dir": str(out_dir)})
    assert r.status_code == 200

    # Corrupt or remove meta.parquet to trigger router_meta_readable False
    meta = out_dir / "router" / "meta.parquet"
    if meta.exists():
        meta.write_bytes(b"")  # empty file should fail parquet reader

    rr = client.get("/readyz", params={"db_path": str(out_dir)})
    assert rr.status_code == 200
    checks = rr.json()["checks"]
    assert checks.get("router_meta_readable") is False
    # With unreadable meta, ids subset check should be False as well
    assert checks.get("router_ids_in_manifest") is False
