from __future__ import annotations

from pathlib import Path
from fastapi.testclient import TestClient

from app.main import app


def test_get_db_receipt_success(tmp_path: Path):
    client = TestClient(app)
    data_dir = Path(__file__).resolve().parents[2] / "sample_data" / "docs"
    out_dir = tmp_path / "db"
    r = client.post("/v1/latticedb/ingest", json={"input_dir": str(data_dir), "out_dir": str(out_dir)})
    assert r.status_code == 200
    resp = client.get("/v1/db/receipt", params={"db_path": str(out_dir)})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload.get("version") == "1"
    assert isinstance(payload.get("db_root"), str) and payload.get("db_root")
