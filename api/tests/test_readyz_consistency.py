from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


def test_readyz_counts_and_ids_subset(tmp_path):
    client = TestClient(app)

    data_dir = Path(__file__).resolve().parents[2] / "sample_data" / "docs"
    out_dir = tmp_path / "db"

    # Ingest to create artifacts
    r = client.post(
        "/v1/latticedb/ingest",
        json={"input_dir": str(data_dir), "out_dir": str(out_dir)},
    )
    assert r.status_code == 200

    # Initial readiness should be true and new checks true
    resp = client.get("/readyz", params={"db_path": str(out_dir)})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ready"] is True
    checks = payload["checks"]
    assert checks.get("router_counts_consistent") is True
    assert checks.get("router_ids_in_manifest") is True

    # Tamper centroids to break count consistency by appending one full vector (dim*4 bytes)
    centroids = out_dir / "router" / "centroids.f32"
    assert centroids.exists()
    cfg = out_dir / "receipts" / "config.json"
    import json
    dim = 32
    if cfg.exists():
        try:
            dim = int(json.loads(cfg.read_text()).get("dim", 32))
        except Exception:
            dim = 32
    bytes_per = dim * 4
    with centroids.open("ab") as f:
        f.write(b"\x00" * bytes_per)

    resp2 = client.get("/readyz", params={"db_path": str(out_dir)})
    assert resp2.status_code == 200
    p2 = resp2.json()
    # At least the counts should now be inconsistent, resulting in not ready
    assert p2["checks"].get("router_counts_consistent") is False
    assert p2["ready"] is False
