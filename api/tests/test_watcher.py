from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from latticedb.watcher import single_scan


def _write_minimal_db_with_centroids(db: Path, dim: int = 2):
    (db / "router").mkdir(parents=True)
    (db / "receipts").mkdir(parents=True)
    C = np.eye(dim, dtype=np.float32)
    (db / "router" / "centroids.f32").write_bytes(C.tobytes())
    (db / "receipts" / "config.json").write_text(json.dumps({"embed_dim": dim}))


def test_single_scan_promotes_backends_and_writes_receipts(tmp_path: Path, monkeypatch):
    # Prepare small input with two tiny files to trigger promotions in firm.demo.yaml thresholds
    inp = tmp_path / "assets"
    (inp / "s1").mkdir(parents=True)
    (inp / "s2").mkdir(parents=True)
    (inp / "s1" / "a.txt").write_text("alpha\n" * 3)
    (inp / "s2" / "b.txt").write_text("beta\n" * 3)

    db = tmp_path / "db"
    _write_minimal_db_with_centroids(db, dim=2)

    # Force build_faiss_index_for_shard to raise once to exercise sealed=False path
    from latticedb import watcher as wt
    called = {"n": 0}

    def boom(*args, **kwargs):
        called["n"] += 1
        raise RuntimeError("boom")

    monkeypatch.setattr(wt, "build_faiss_index_for_shard", boom)

    # Use the demo firm config with tiny thresholds to promote to faiss
    firm_demo = Path(__file__).resolve().parents[2] / "firm.demo.yaml"
    out = single_scan(inp, db, firm_path=firm_demo)
    assert out["count"] >= 2
    # Composite and DB receipts written
    assert (db / "receipts" / "composite.receipt.json").exists()
    assert (db / "receipts" / "db_receipt.json").exists()
    # Ensure our fail path was hit at least once (some shard attempted to build)
    assert called["n"] >= 1
