from __future__ import annotations

from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from app import main as m


def test_readyz_manifest_exists_without_meta_sets_router_ids_in_manifest_false(tmp_path: Path):
    client = TestClient(m.app)

    # Create a minimal DB dir where manifest exists but router/meta.parquet does not
    db = tmp_path / "db"
    db.mkdir(parents=True)
    (db / "router").mkdir(parents=True)
    (db / "receipts").mkdir(parents=True)

    # Create an empty manifest with the lattice_id column so read_parquet succeeds
    man_df = pd.DataFrame({"lattice_id": pd.Series(dtype=str)})
    man_df.to_parquet(db / "manifest.parquet")

    # Ensure router/meta.parquet is intentionally missing and centroids not required for this branch
    resp = client.get("/readyz", params={"db_path": str(db)})
    assert resp.status_code == 200
    payload = resp.json()
    checks = payload["checks"]
    assert checks.get("manifest_exists") is True
    assert checks.get("router_meta_readable") is False  # meta missing => not readable
    # With manifest present but no meta, router_ids_in_manifest should be False
    assert checks.get("router_ids_in_manifest") is False
    # Overall ready should be false given missing meta and other checks
    assert payload["ready"] is False


def test_api_key_mismatch_returns_401(tmp_path: Path):
    client = TestClient(m.app)

    # Snapshot and enable API key requirement with a known secret
    snap = (m.settings.jwt_enabled, m.settings.api_key_required, m.settings.api_key)
    try:
        m.settings.jwt_enabled = False
        m.settings.api_key_required = True
        m.settings.api_key = "secret-123"

        # Call a protected endpoint with a wrong API key; dependency should reject before handler runs
        inp = tmp_path / "in"
        out = tmp_path / "out"
        inp.mkdir(parents=True)
        r = client.post(
            "/v1/latticedb/ingest",
            json={"input_dir": str(inp), "out_dir": str(out)},
            headers={"X-API-Key": "wrong"},
        )
        assert r.status_code == 401
        assert r.json().get("detail") == "invalid api key"
    finally:
        m.settings.jwt_enabled, m.settings.api_key_required, m.settings.api_key = snap
