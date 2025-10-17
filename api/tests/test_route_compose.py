from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


def test_route_returns_empty_when_database_missing(tmp_path):
    client = TestClient(app)
    resp = client.post(
        "/v1/latticedb/route",
        json={
            "db_path": str(tmp_path / "db"),
            "q": "missing",
            "k_lattices": 5,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["candidates"] == []


def test_compose_unknown_lattice_ids(tmp_path):
    client = TestClient(app)
    data_dir = Path(__file__).resolve().parents[2] / "sample_data" / "docs"
    out_dir = tmp_path / "db"

    ingest_resp = client.post(
        "/v1/latticedb/ingest",
        json={"input_dir": str(data_dir), "out_dir": str(out_dir)},
    )
    assert ingest_resp.status_code == 200
    db_root = ingest_resp.json()["db_root"]

    compose_resp = client.post(
        "/v1/latticedb/compose",
        json={
            "db_path": str(out_dir),
            "q": "What is Oscillink?",
            "lattice_ids": ["L-DOES-NOT-EXIST"],
        },
    )
    assert compose_resp.status_code == 200
    payload = compose_resp.json()["context_pack"]
    assert payload["question"] == "What is Oscillink?"
    assert payload["working_set"] == []
    comp_receipt = payload["receipts"]["composite"]
    assert comp_receipt["lattice_ids"] == []
    assert comp_receipt["deltaH_total"] == 0.0
    assert comp_receipt["db_root"] == db_root
