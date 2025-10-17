from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from latticedb.receipts import CompositeReceipt  # type: ignore[import]


def _collect_lattice_receipts(root: Path) -> dict[str, dict]:
    receipts: dict[str, dict] = {}
    for receipt_path in (root / "groups").glob("*/*/receipt.json"):
        payload = json.loads(receipt_path.read_text())
        receipts[payload["lattice_id"]] = payload
    return receipts


def test_verify_endpoint_missing_db_receipt(tmp_path):
    client = TestClient(app)

    composite = CompositeReceipt.build(
        db_root="missing",
        lattice_ids=[],
        edge_hash_composite="stub",
        deltaH_total=0.0,
        cg_iters=0,
        final_residual=0.0,
        epsilon=1e-3,
        tau=0.3,
        filters={},
        model_sha256="stub-model-sha256",
    ).model_dump()

    payload = {
        "db_path": str(tmp_path / "nonexistent"),
        "composite": composite,
        "lattice_receipts": {},
    }

    resp = client.post("/v1/latticedb/verify", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["verified"] is False
    assert body["reason"] == "db_receipt missing"


def test_verify_endpoint_detects_tampered_composite(tmp_path):
    client = TestClient(app)
    data_dir = Path(__file__).resolve().parents[2] / "sample_data" / "docs"
    out_dir = tmp_path / "db"

    ingest_resp = client.post(
        "/v1/latticedb/ingest",
        json={"input_dir": str(data_dir), "out_dir": str(out_dir)},
    )
    assert ingest_resp.status_code == 200

    route_resp = client.post(
        "/v1/latticedb/route",
        json={"db_path": str(out_dir), "q": "What is Oscillink?", "k_lattices": 4},
    )
    assert route_resp.status_code == 200
    candidates = route_resp.json()["candidates"]
    assert candidates
    selected_ids = [cand["lattice_id"] for cand in candidates][:2]

    compose_resp = client.post(
        "/v1/latticedb/compose",
        json={
            "db_path": str(out_dir),
            "q": "What is Oscillink?",
            "lattice_ids": selected_ids,
        },
    )
    assert compose_resp.status_code == 200
    composite = compose_resp.json()["context_pack"]["receipts"]["composite"]

    lattice_receipts = _collect_lattice_receipts(out_dir)
    payload = {
        "db_path": str(out_dir),
        "composite": {**composite, "state_sig": "0" * 64},
        "lattice_receipts": {
            lid: lattice_receipts[lid]
            for lid in composite["lattice_ids"]
            if lid in lattice_receipts
        },
    }
    assert payload["lattice_receipts"]

    resp = client.post("/v1/latticedb/verify", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["verified"] is False
    assert body["reason"] == "composite state_sig mismatch"
