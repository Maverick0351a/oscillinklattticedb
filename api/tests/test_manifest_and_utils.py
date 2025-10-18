from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from latticedb.utils import Manifest


def test_manifest_filters_sort_and_time_window(tmp_path: Path):
    client = TestClient(app)
    data_dir = Path(__file__).resolve().parents[2] / "sample_data" / "docs"
    out_dir = tmp_path / "db"
    r = client.post("/v1/latticedb/ingest", json={"input_dir": str(data_dir), "out_dir": str(out_dir)})
    assert r.status_code == 200

    # Sort by deltaH_total desc
    resp = client.get("/v1/latticedb/manifest", params={"db_path": str(out_dir), "sort_by": "deltaH_total", "sort_order": "desc"})
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) > 0
    # Time window filter around now
    now = datetime.now(timezone.utc)
    frm = (now - timedelta(days=1)).isoformat()
    to = (now + timedelta(days=1)).isoformat()
    resp2 = client.get("/v1/latticedb/manifest", params={"db_path": str(out_dir), "created_from": frm, "created_to": to})
    assert resp2.status_code == 200
    items2 = resp2.json()["items"]
    assert len(items2) == len(items)


def test_ingest_dedup_skip_generates_wal(tmp_path: Path):
    client = TestClient(app)
    # Create a tiny input dir with a single file
    inp = tmp_path / "input"
    inp.mkdir(parents=True)
    (inp / "a.txt").write_text("hello\nworld\n" * 3)
    out = tmp_path / "db"
    r1 = client.post("/v1/latticedb/ingest", json={"input_dir": str(inp), "out_dir": str(out)})
    assert r1.status_code == 200
    # Second ingest should skip file via dedup and append WAL entries
    r2 = client.post("/v1/latticedb/ingest", json={"input_dir": str(inp), "out_dir": str(out)})
    assert r2.status_code == 200
    wal = out / "receipts" / "ingest.wal.jsonl"
    assert wal.exists()
    # Ensure at least one dedup_skip entry is present
    lines = [json.loads(ln) for ln in wal.read_text().splitlines() if ln.strip()]
    assert any(li.get("event") == "dedup_skip" for li in lines)


def test_manifest_append_and_list(tmp_path: Path):
    man = Manifest(tmp_path)
    man.append([
        {"group_id": "G-1", "lattice_id": "L-1", "deltaH_total": 0.1, "created_at": datetime.now(timezone.utc).isoformat()},
    ])
    man.append([
        {"group_id": "G-2", "lattice_id": "L-2", "deltaH_total": 0.2, "created_at": datetime.now(timezone.utc).isoformat()},
    ])
    rows = man.list_lattices()
    assert {r["lattice_id"] for r in rows} == {"L-1", "L-2"}
