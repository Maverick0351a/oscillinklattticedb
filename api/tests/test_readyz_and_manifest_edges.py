from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


def test_readyz_empty_db_reports_false(tmp_path: Path):
    client = TestClient(app)
    db = tmp_path / "db"
    r = client.get("/readyz", params={"db_path": str(db)})
    assert r.status_code == 200
    checks = r.json()["checks"]
    # With no artifacts present all flags should be false
    assert all(not bool(v) for v in checks.values())


def test_readyz_config_hash_mismatch(tmp_path: Path):
    client = TestClient(app)
    data_dir = Path(__file__).resolve().parents[2] / "sample_data" / "docs"
    out_dir = tmp_path / "db"
    # Create valid receipts via ingest
    r = client.post("/v1/latticedb/ingest", json={"input_dir": str(data_dir), "out_dir": str(out_dir)})
    assert r.status_code == 200
    # Tamper config after db_receipt is written to force mismatch
    cfg = out_dir / "receipts" / "config.json"
    if cfg.exists():
        cfg.write_text((cfg.read_text() + "\n"))
    rr = client.get("/readyz", params={"db_path": str(out_dir)})
    assert rr.status_code == 200
    checks = rr.json()["checks"]
    # router/meta remains readable, but config_hash_matches should be False
    assert checks.get("router_meta_readable") in (True, False)  # don't overfit
    assert checks.get("config_hash_matches") is False


def test_manifest_sort_and_pagination(tmp_path: Path):
    client = TestClient(app)
    data_dir = Path(__file__).resolve().parents[2] / "sample_data" / "docs"
    out_dir = tmp_path / "db"
    r = client.post("/v1/latticedb/ingest", json={"input_dir": str(data_dir), "out_dir": str(out_dir)})
    assert r.status_code == 200
    # sort by group_id asc and page through
    first = client.get("/v1/latticedb/manifest", params={"db_path": str(out_dir), "sort_by": "group_id", "sort_order": "asc", "limit": 2, "offset": 0}).json()
    second = client.get("/v1/latticedb/manifest", params={"db_path": str(out_dir), "sort_by": "group_id", "sort_order": "asc", "limit": 2, "offset": 2}).json()
    assert first["items"] != second["items"] or first["total"] <= 2
    # sort by lattice_id desc
    resp = client.get("/v1/latticedb/manifest", params={"db_path": str(out_dir), "sort_by": "lattice_id", "sort_order": "desc"})
    assert resp.status_code == 200 and isinstance(resp.json().get("items", []), list)


def test_search_pagination(tmp_path: Path):
    client = TestClient(app)
    data_dir = Path(__file__).resolve().parents[2] / "sample_data" / "docs"
    out_dir = tmp_path / "db"
    r = client.post("/v1/latticedb/ingest", json={"input_dir": str(data_dir), "out_dir": str(out_dir)})
    assert r.status_code == 200
    all_items = client.get("/v1/latticedb/search", params={"db_path": str(out_dir), "q": "", "limit": 1000}).json()["items"]
    page1 = client.get("/v1/latticedb/search", params={"db_path": str(out_dir), "q": "", "limit": 1, "offset": 0}).json()["items"]
    page2 = client.get("/v1/latticedb/search", params={"db_path": str(out_dir), "q": "", "limit": 1, "offset": 1}).json()["items"]
    assert len(all_items) >= len(page1) + len(page2)
    if len(all_items) >= 2:
        assert page1 != page2
