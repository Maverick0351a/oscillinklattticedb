from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


def test_ingest_route_compose_verify(tmp_path):
    """Exercise the primary lattice workflow and guard the happy path."""
    client = TestClient(app)

    data_dir = Path(__file__).resolve().parents[2] / "sample_data" / "docs"
    out_dir = tmp_path / "db"

    ingest_resp = client.post(
        "/v1/latticedb/ingest",
        json={"input_dir": str(data_dir), "out_dir": str(out_dir)},
    )
    assert ingest_resp.status_code == 200
    ingest_data = ingest_resp.json()
    assert ingest_data["count"] > 0

    db_receipt_path = out_dir / "receipts" / "db_receipt.json"
    assert db_receipt_path.exists()
    stored_root = json.loads(db_receipt_path.read_text())
    assert stored_root["db_root"] == ingest_data["db_root"]

    route_resp = client.post(
        "/v1/latticedb/route",
        json={"db_path": str(out_dir), "q": "What is Oscillink?", "k_lattices": 3},
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
    context_pack = compose_resp.json()["context_pack"]
    assert context_pack["question"] == "What is Oscillink?"
    comp_receipt = context_pack["receipts"]["composite"]
    assert comp_receipt["state_sig"]
    assert comp_receipt["db_root"] == ingest_data["db_root"]

    lattice_receipts: dict[str, dict] = {}
    for rec_path in (out_dir / "groups").glob("*/*/receipt.json"):
        payload = json.loads(rec_path.read_text())
        lattice_receipts[payload["lattice_id"]] = payload

    verify_payload = {
        "db_path": str(out_dir),
        "composite": comp_receipt,
        "lattice_receipts": {
            lid: lattice_receipts[lid]
            for lid in comp_receipt["lattice_ids"]
            if lid in lattice_receipts
        },
    }
    assert verify_payload["lattice_receipts"], "lattice receipts should be present"

    verify_resp = client.post("/v1/latticedb/verify", json=verify_payload)
    assert verify_resp.status_code == 200
    verify_data = verify_resp.json()
    assert verify_data["verified"] is True
    assert verify_data["reason"] == "ok"
