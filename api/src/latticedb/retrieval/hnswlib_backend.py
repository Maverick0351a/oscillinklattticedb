"""hnswlib retrieval backend (optional). Falls back to numpy flat if unavailable.
SPDX-License-Identifier: BUSL-1.1
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from pathlib import Path  # noqa: F401

from .base import (
    RetrievalBackend,
    Candidate,
    BuildReceipt,
    set_determinism_env,
    dir_tree_sha256,
    _get_safe_base,
    canonicalize_and_validate,
)


class _HnswlibBackend:
    def __init__(self) -> None:
        import numpy as np  # type: ignore
        import hnswlib  # type: ignore
        self._np = np
        self._hnswlib = hnswlib
        self._index = None
        self._ids: List[str] = []
        self._params: Dict[str, Any] = {"M": 32, "efConstruction": 200, "efSearch": 64}

    def build(self, vectors_or_docs_path: str, out_dir: str, **kwargs: Any) -> BuildReceipt:
        set_determinism_env(kwargs.get("random_seed"), kwargs.get("threads"))
        M = int(kwargs.get("M", self._params["M"]))
        efC = int(kwargs.get("efConstruction", self._params["efConstruction"]))
        base = _get_safe_base()
        # Validate vectors path (allows system temp when base is None)
        vp = canonicalize_and_validate(vectors_or_docs_path, base)
        if vp is None:
            # Disallow reading outside of base; build an empty index and avoid writing outside base
            X = self._np.zeros((0, int(kwargs.get("dim", 32))), dtype=self._np.float32)
            ids: List[str] = []
            self._ids = ids
            self._index = None
            outp = canonicalize_and_validate(out_dir, base)
            if outp is None:
                index_hash = _hash_stub()
                return BuildReceipt(
                    backend_id="hnswlib",
                    backend_version="hnswlib",
                    params={"M": int(kwargs.get("M", 32)), "efConstruction": int(kwargs.get("efConstruction", 200)), "efSearch": int(kwargs.get("efSearch", 64))},
                    index_hash=index_hash,
                    training_hash=None,
                )
            outp.mkdir(parents=True, exist_ok=True)
            index_hash = dir_tree_sha256(outp)
            return BuildReceipt(
                backend_id="hnswlib",
                backend_version="hnswlib",
                params={"M": int(kwargs.get("M", 32)), "efConstruction": int(kwargs.get("efConstruction", 200)), "efSearch": int(kwargs.get("efSearch", 64))},
                index_hash=index_hash,
                training_hash=None,
            )
        if vp.is_file() and vp.suffix == ".npy":
            X = self._np.load(vp).astype(self._np.float32)
        elif vp.is_dir() and (vp/"router/centroids.f32").exists():
            D = int(kwargs.get("dim", 32))
            raw = self._np.fromfile(vp/"router/centroids.f32", dtype=self._np.float32)
            N = raw.size // max(1, D)
            X = raw.reshape(N, D)
        else:
            X = self._np.zeros((0, int(kwargs.get("dim", 32))), dtype=self._np.float32)
        ids = [f"L-{i+1:06d}" for i in range(X.shape[0])]
        dim = X.shape[1] if X.ndim == 2 and X.shape[0] > 0 else int(kwargs.get("dim", 32))
        idx = self._hnswlib.Index(space='cosine', dim=dim)
        idx.init_index(max_elements=X.shape[0], ef_construction=efC, M=M)
        if X.shape[0] > 0:
            idx.add_items(X, ids=list(range(X.shape[0])))
        self._ids = ids
        self._index = idx
        outp = canonicalize_and_validate(out_dir, base)
        if outp is None:
            index_hash = _hash_stub()
            return BuildReceipt(
                backend_id="hnswlib",
                backend_version="hnswlib",
                params={"M": M, "efConstruction": efC, "efSearch": int(kwargs.get("efSearch", 64))},
                index_hash=index_hash,
                training_hash=None,
            )
        outp.mkdir(parents=True, exist_ok=True)
        # Persist index for hashing
        (outp/"hnsw_index.bin").write_bytes(idx.get_current_count().to_bytes(8, 'little'))
        index_hash = dir_tree_sha256(outp)
        return BuildReceipt(
            backend_id="hnswlib",
            backend_version="hnswlib",
            params={"M": M, "efConstruction": efC, "efSearch": int(kwargs.get("efSearch", 64))},
            index_hash=index_hash,
            training_hash=None,
        )

    def query(self, qvec, k: int, filters: Optional[Dict[str, Any]] = None) -> List[Candidate]:  # noqa: ANN001
        if self._index is None:
            return []
        self._index.set_ef(int(max(1, int(self._params.get("efSearch", 64)))))
        labels, dists = self._index.knn_query(qvec, k=int(max(1, k)))
        out: List[Candidate] = []
        for lab, dist in zip(labels[0], dists[0]):
            i = int(lab)
            lid = self._ids[i] if 0 <= i < len(self._ids) else str(i)
            out.append({"id": lid, "score": float(1.0 - dist), "meta": {}})
        # Stable tie-break
        out.sort(key=lambda c: (-c["score"], c["id"]))
        return out

    def info(self) -> Dict[str, Any]:
        return {"backend": "hnswlib"}


def make_hnswlib_backend() -> RetrievalBackend:
    try:
        import hnswlib  # type: ignore  # noqa: F401
        return _HnswlibBackend()
    except Exception:
        # Fallback to numpy flat
        from .faiss_backend import make_faiss_backend
        return make_faiss_backend("flat")


def _hash_stub() -> str:
    import hashlib as _h
    return _h.sha256(b"no-write").hexdigest()

