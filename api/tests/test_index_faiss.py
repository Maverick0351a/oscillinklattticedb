from __future__ import annotations

import sys
import types
import json
import numpy as np
from pathlib import Path

from latticedb.index_faiss import build_faiss_index_for_shard


class _MockIndex:
    def __init__(self, d: int):
        self.d = d
        self.vecs = None

    def add(self, X: np.ndarray):
        # store a copy to simulate persistence
        self.vecs = X.copy()


def _mock_faiss_module(tmp_dir: Path):
    mod = types.ModuleType("faiss")
    def IndexFlatL2(d):
        return _MockIndex(d)
    def write_index(index, path: str):
        # write minimal bytes to allow checksum calculation
        with open(path, "wb") as f:
            data = index.vecs.tobytes() if getattr(index, "vecs", None) is not None else b""
            f.write(data)
    mod.IndexFlatL2 = IndexFlatL2  # type: ignore[attr-defined]
    mod.write_index = write_index  # type: ignore[attr-defined]
    sys.modules["faiss"] = mod


def _write_router_centroids(db_root: Path, C: np.ndarray, ids: list[str]):
    (db_root / "router").mkdir(parents=True)
    (db_root / "receipts").mkdir(parents=True)
    (db_root / "router" / "centroids.f32").write_bytes(C.astype("float32").tobytes())
    # config to specify dim
    (db_root / "receipts" / "config.json").write_text(json.dumps({"embed_dim": int(C.shape[1])}))
    # meta parquet with duplicate IDs to test dedup
    import pandas as pd
    df = pd.DataFrame({"lattice_id": ids})
    df.to_parquet(db_root / "router" / "meta.parquet")


def test_build_faiss_index_for_shard_with_dedup(tmp_path: Path):
    db = tmp_path / "db"
    C = np.array([[1, 0, 0, 0], [1, 0, 0, 0]], dtype=np.float32)  # duplicate vectors/ids
    _mock_faiss_module(tmp_path)
    _write_router_centroids(db, C, ["L-000001", "L-000001"])  # duplicate lattice_id

    res = build_faiss_index_for_shard(db, "shard-root")
    # Sealed paths exist
    assert res.index_path.exists()
    assert res.meta_path.exists()
    assert res.postings_path.exists()
    # Dedup reduces nvec to 1
    assert res.nvec == 1
    assert res.dim == 4
