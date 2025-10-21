from __future__ import annotations

from typing import Tuple

import numpy as np

from latticedb.retrieval.base import resolve_backend, RetrievalBackend
import os
from latticedb.retrieval.faiss_backend import make_faiss_backend
from latticedb.retrieval.hybrid import make_hybrid_backend


def test_resolve_backend_variants():
    bid, inst, params = resolve_backend("faiss:flat")
    assert bid == "faiss:flat"
    assert hasattr(inst, "query")
    assert isinstance(params, dict)

    bid, inst, _ = resolve_backend("hnswlib")
    # May fallback to faiss:flat if hnswlib not installed
    assert bid in ("hnswlib", "faiss:flat")
    assert hasattr(inst, "query")

    bid, inst, _ = resolve_backend("bm25")
    assert bid == "bm25:tantivy"
    assert hasattr(inst, "query")


def _build_dummy_index(tmp_path) -> Tuple[RetrievalBackend, np.ndarray]:
    # Build a tiny numpy-backed flat index on 4 items in 3D
    X = np.array(
        [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
            [1.0, 1.0, 0.0],
        ],
        dtype=np.float32,
    )
    b = make_faiss_backend("flat")
    # Configure safe base to the tmp dir and use relative paths under it
    base = tmp_path
    os.environ["LATTICEDB_DB_ROOT"] = str(base)
    # Save to .npy so build can load
    npy = base / "vecs.npy"
    np.save(npy, X)
    _ = b.build("vecs.npy", "out")
    return b, X


def test_flat_backend_query_and_tie_break(tmp_path):
    b, X = _build_dummy_index(tmp_path)
    # Query aligned with the first basis vector
    q = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    res = b.query(q, k=3)
    # Expect the first id on top deterministically
    assert len(res) == 3
    assert res[0]["id"].startswith("L-000001")
    assert res[0]["score"] >= res[1]["score"] >= res[2]["score"]

    # Dimension mismatch should raise a clear ValueError
    q_bad = np.array([1.0, 0.0], dtype=np.float32)
    try:
        _ = b.query(q_bad, k=1)
        assert False, "Expected ValueError for dimension mismatch"
    except ValueError as e:  # noqa: PT011
        assert "dimension mismatch" in str(e)


def test_hybrid_backend_determinism(tmp_path):
    # Hybrid of vector flat + bm25 (stub) should return vector ordering when bm25 empty
    inst, meta = make_hybrid_backend("vec=0.8,lex=0.2")
    assert meta["weights"]["vec"] == 0.8
    # Build using the same dummy vectors
    X = np.array(
        [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float32,
    )
    base = tmp_path
    os.environ["LATTICEDB_DB_ROOT"] = str(base)
    npy = base / "vecs.npy"
    np.save(npy, X)
    _ = inst.build("vecs.npy", "out")
    q = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    res = inst.query(q, k=2)
    assert len(res) == 2
    assert res[0]["id"].startswith("L-000001")
    # Scores must be monotonic non-increasing and deterministic
    assert res[0]["score"] >= res[1]["score"]


def test_hybrid_weight_parsing_variants():
    # Colon-free short form
    inst1, meta1 = make_hybrid_backend("0.7vec,0.3bm25")
    assert abs(meta1["weights"]["vec"] - 0.7) < 1e-9
    assert abs(meta1["weights"]["lex"] - 0.3) < 1e-9
    # Explicit key form
    inst2, meta2 = make_hybrid_backend("vec=0.6,lex=0.4")
    assert abs(meta2["weights"]["vec"] - 0.6) < 1e-9
    assert abs(meta2["weights"]["lex"] - 0.4) < 1e-9


def test_resolve_backend_unknown_fallback():
    bid, inst, params = resolve_backend("unknown:thing")
    assert bid == "faiss:flat"
    assert hasattr(inst, "query")
    assert isinstance(params, dict)
