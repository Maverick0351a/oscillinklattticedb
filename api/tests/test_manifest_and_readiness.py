from __future__ import annotations

import json
import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


def test_manifest_config_and_readyz(tmp_path):
    client = TestClient(app)

    data_dir = Path(__file__).resolve().parents[2] / "sample_data" / "docs"
    out_dir = tmp_path / "db"

    # Ingest to create artifacts
    r = client.post(
        "/v1/latticedb/ingest",
        json={"input_dir": str(data_dir), "out_dir": str(out_dir)},
    )
    assert r.status_code == 200

    # Manifest exists and contains the lattice ids from receipts
    manifest = out_dir / "manifest.parquet"
    assert manifest.exists()
    import pandas as pd

    man = pd.read_parquet(manifest)
    assert "lattice_id" in man.columns and len(man) > 0
    # New schema fields
    for col in [
        "created_at",
        "source_file",
        "chunk_count",
        "file_bytes",
        "file_sha256",
    ]:
        assert col in man.columns

    # Config hash matches db_receipt
    cfg = out_dir / "receipts" / "config.json"
    assert cfg.exists()
    cfg_hash = hashlib.sha256(cfg.read_bytes()).hexdigest()

    db_receipt = out_dir / "receipts" / "db_receipt.json"
    assert db_receipt.exists()
    dr = json.loads(db_receipt.read_text())
    assert dr.get("config_hash") == cfg_hash

    # Readiness probe returns ready true and checks
    ready = client.get("/readyz", params={"db_path": str(out_dir)})
    assert ready.status_code == 200
    payload = ready.json()
    assert payload["ready"] is True
    checks = payload["checks"]
    expected = [
        "router_centroids_exists",
        "router_meta_exists",
        "db_receipt_exists",
        "config_exists",
        "manifest_exists",
        "config_hash_matches",
        "router_meta_readable",
    ]
    for k in expected:
        assert checks.get(k) is True
