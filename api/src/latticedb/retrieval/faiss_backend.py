"""FAISS retrieval backend with a numpy flat fallback.
SPDX-License-Identifier: BUSL-1.1

This is a minimal, optional adapter. It is intentionally conservative to avoid
introducing heavy dependencies unless the user opts in.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from pathlib import Path  # noqa: F401  # kept for type hints in comments if needed

from .base import (
    RetrievalBackend,
    Candidate,
    BuildReceipt,
    set_determinism_env,
    dir_tree_sha256,
    _get_safe_base,
    canonicalize_and_validate,
)


class _NumpyFlatBackend:
    def __init__(self) -> None:
        import numpy as np  # type: ignore
        self._np = np
        self._X = None  # type: ignore
        self._ids: List[str] = []
        self._params: Dict[str, Any] = {"mode": "flat", "impl": "numpy"}

    def build(self, vectors_or_docs_path: str, out_dir: str, **kwargs: Any) -> BuildReceipt:
        set_determinism_env(kwargs.get("random_seed"), kwargs.get("threads"))
        base = _get_safe_base()
        # Validate vectors/docs path against base (or temp-only allowance when base is None)
        vp = canonicalize_and_validate(vectors_or_docs_path, base)
        if vp is None:
            # Disallow access; build an empty index deterministically
            X = self._np.zeros((0, int(kwargs.get("dim", 32))), dtype=self._np.float32)
            self._X = X
            self._ids = []
            outp = canonicalize_and_validate(out_dir, base) if out_dir else None
            if outp is None:
                index_hash = _hash_stub()
                return BuildReceipt(
                    backend_id="faiss:flat",
                    backend_version="numpy-fallback",
                    params=self._params,
                    index_hash=index_hash,
                    training_hash=None,
                )
            outp.mkdir(parents=True, exist_ok=True)
            index_hash = dir_tree_sha256(outp)
            return BuildReceipt(
                backend_id="faiss:flat",
                backend_version="numpy-fallback",
                params=self._params,
                index_hash=index_hash,
                training_hash=None,
            )
        # With a validated path, only allow reading specific filenames/locations
        X = None
        ids: List[str] = []
        if vp is not None and vp.suffix == ".npy" and vp.is_file():
            X = self._np.load(vp)
        elif vp is not None and vp.is_dir() and (vp/"router/centroids.f32").exists():
            raw = self._np.fromfile(vp/"router/centroids.f32", dtype=self._np.float32)
            # Best effort: guess dim
            D = int(kwargs.get("dim", 32))
            N = raw.size // max(1, D)
            X = raw.reshape(N, D)
            ids = [f"L-{i+1:06d}" for i in range(N)]
        else:
            X = self._np.zeros((0, int(kwargs.get("dim", 32))), dtype=self._np.float32)
        self._X = X.astype(self._np.float32)
        self._ids = ids or [f"L-{i+1:06d}" for i in range(self._X.shape[0])]
        outp = canonicalize_and_validate(out_dir, base)
        if outp is None:
            # Do not write outside of base
            index_hash = _hash_stub()
            return BuildReceipt(
                backend_id="faiss:flat",
                backend_version="numpy-fallback",
                params=self._params,
                index_hash=index_hash,
                training_hash=None,
            )
        outp.mkdir(parents=True, exist_ok=True)
        index_hash = dir_tree_sha256(outp)
        return BuildReceipt(
            backend_id="faiss:flat",
            backend_version="numpy-fallback",
            params=self._params,
            index_hash=index_hash,
            training_hash=None,
        )

    def query(self, qvec, k: int, filters: Optional[Dict[str, Any]] = None) -> List[Candidate]:  # noqa: ANN001
        X = self._X
        if X is None or X.shape[0] == 0:
            return []
        # Ensure 1-D query vector and dimensionality match
        v = self._np.asarray(qvec, dtype=self._np.float32)
        if v.ndim == 2 and v.shape[0] == 1:
            v = v[0]
        if v.ndim != 1:
            raise ValueError("qvec must be a 1-D vector")
        if v.shape[0] != X.shape[1]:
            raise ValueError(f"dimension mismatch: expected {X.shape[1]}, got {v.shape[0]}")

        # Cosine similarity with stable tie-breaking by (-score, id)
        v = v / (self._np.linalg.norm(v) + 1e-9)
        Y = X / (self._np.linalg.norm(X, axis=1, keepdims=True) + 1e-9)
        sims = (Y @ v).astype(self._np.float32)
        # Build candidate list and sort deterministically
        pairs = [(float(sims[i]), self._ids[i], i) for i in range(X.shape[0])]
        pairs.sort(key=lambda t: (-t[0], t[1]))
        out: List[Candidate] = []
        for score, lid, i in pairs[: int(max(1, k))]:
            out.append({"id": lid, "score": float(score), "meta": {}})
        return out

    def info(self) -> Dict[str, Any]:
        return {"backend": "faiss:flat", "impl": "numpy"}


def make_faiss_backend(mode: str) -> RetrievalBackend:
    mode = (mode or "flat").lower()
    if mode != "flat":
        # For now, only ship flat exact search; ANN modes require full faiss setup
        mode = "flat"
    try:
        import faiss  # type: ignore  # noqa: F401
        # Placeholder: In a future iteration, return a proper FAISS-backed implementation
        # For now, we still use the numpy flat fallback but expose a version hint
        b = _NumpyFlatBackend()
        b._params.update({"faiss_available": True})
        return b
    except Exception:
        return _NumpyFlatBackend()


def _hash_stub() -> str:
    import hashlib as _h
    return _h.sha256(b"no-write").hexdigest()

