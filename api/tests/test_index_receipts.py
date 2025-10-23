from pathlib import Path
from latticedb.validators import validate_index_receipts
import json

def test_index_receipts_missing(tmp_path: Path):
    db = tmp_path / "db"
    sealed = db / "indexes" / "S-000001" / "sealed"
    sealed.mkdir(parents=True, exist_ok=True)
    warns = validate_index_receipts(db, limit=10)
    # Should warn missing receipt
    assert any(w.startswith("index_receipt_missing:") for w in warns)


def test_index_receipts_present(tmp_path: Path):
    db = tmp_path / "db"
    sealed = db / "indexes" / "S-000001" / "sealed"
    sealed.mkdir(parents=True, exist_ok=True)
    receipt = {
        "version": 1,
        "backend_id": "faiss_flat_l2",
        "index_hash": "abc123",
        "params": {"type": "flat_l2", "dim": 32},
    }
    (sealed / "index_receipt.json").write_text(json.dumps(receipt))
    warns = validate_index_receipts(db, limit=10)
    # No warnings about missing/unreadable receipts
    assert not any(w.startswith("index_receipt_missing:") or w.startswith("index_receipt_unreadable:") for w in warns)
