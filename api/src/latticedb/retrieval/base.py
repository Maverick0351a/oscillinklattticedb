"""Retrieval backend protocol and deterministic helpers.
SPDX-License-Identifier: BUSL-1.1

This module defines a tiny, auditable interface for retrieval backends so users can
swap in FAISS/HNSW/BM25 adapters without changing the composer.

Contract (inputs/outputs):
- build(vectors_or_docs_path, out_dir, **kwargs) -> BuildReceipt (includes params and index hash)
- query(qvec: np.ndarray, k: int, filters: dict|None) -> list[Candidate]
- info() -> dict: basic metadata for receipts

Determinism rules:
- Stable tie-breaking by (-score, id)
- Optional seeding via set_determinism_env (threads and seeds)
- Index hash computed over on-disk artifacts (sorted by path)
"""
from __future__ import annotations

from typing import Any, Dict, List, Protocol, TypedDict, Optional, Tuple, Callable
import hashlib
import os
from pathlib import Path

try:
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover - numpy is a hard dep of the project
    np = None  # type: ignore


class Candidate(TypedDict):
    id: str
    score: float
    meta: Dict[str, Any]


class BuildReceipt(TypedDict):
    backend_id: str
    backend_version: str
    params: Dict[str, Any]
    index_hash: str
    training_hash: Optional[str]


class RetrievalBackend(Protocol):
    def build(self, vectors_or_docs_path: str, out_dir: str, **kwargs: Any) -> BuildReceipt: ...

    def query(self, qvec: Any, k: int, filters: Optional[Dict[str, Any]] = None) -> List[Candidate]: ...

    def info(self) -> Dict[str, Any]: ...


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def dir_tree_sha256(root: Path) -> str:
    """Compute a deterministic hash over all files under root (paths sorted)."""
    # Enforce safe base if configured
    try:
        base = _get_safe_base()
        if base is not None and not is_within_base(base, root):
            return _sha256_bytes(b"no-walk")
    except Exception:
        # If safety check fails, avoid walking
        return _sha256_bytes(b"no-walk")
    if not root.exists():
        return _sha256_bytes(b"empty")
    files: List[Path] = []
    for base, _dirs, names in os.walk(root):
        for n in names:
            files.append(Path(base) / n)
    files.sort(key=lambda p: str(p).replace("\\", "/"))
    h = hashlib.sha256()
    for p in files:
        h.update(str(p.relative_to(root)).encode("utf-8"))
        h.update(b"\0")
        h.update(file_sha256(p).encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


# ---- Safe path utilities to mitigate path injection -----------------------

def _get_safe_base() -> Optional[Path]:
    """Resolve a safe base directory from environment.

    If LATTICEDB_DB_ROOT is set, only allow reads/writes under this directory.
    If not set, callers should treat paths as untrusted and avoid filesystem IO.
    """
    try:
        base = os.environ.get("LATTICEDB_DB_ROOT")
        if not base:
            return None
        p = Path(base).resolve()
        return p
    except Exception:
        return None


def is_within_base(base: Path, candidate: Path) -> bool:
    try:
        return candidate.resolve().is_relative_to(base)
    except Exception:
        try:
            # Python <3.9 fallback just in case: compare string prefix of resolved paths
            b = str(base.resolve()).replace("\\", "/")
            c = str(candidate.resolve()).replace("\\", "/")
            return c.startswith(b.rstrip("/") + "/") or c == b
        except Exception:
            return False


def set_determinism_env(seed: int | None = None, threads: int | None = None) -> None:
    """Optionally pin seeds/threads for deterministic builds/queries.

    This function only sets environment variables; libraries should read them if they support it.
    """
    if seed is not None:
        os.environ.setdefault("PYTHONHASHSEED", str(int(seed)))
        os.environ.setdefault("FAISS_SEED", str(int(seed)))
        os.environ.setdefault("HNSW_SEED", str(int(seed)))
    if threads is not None:
        v = str(int(max(1, threads)))
        for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
            os.environ.setdefault(k, v)


# Simple registry for resolving backends by id
_REGISTRY: Dict[str, Callable[[], RetrievalBackend]] = {}


def register_backend(backend_id: str, factory: Callable[[], RetrievalBackend]) -> None:
    _REGISTRY[backend_id] = factory


def available_backends() -> List[str]:
    return sorted(_REGISTRY.keys())


def resolve_backend(spec: str) -> Tuple[str, RetrievalBackend, Dict[str, Any]]:
    """Resolve a backend spec like "faiss:flat" or "hybrid:0.7vec,0.3bm25".

    Returns (backend_id, instance, params).
    """
    parts = spec.split(":", 1)
    backend_key = parts[0].strip().lower()
    extra = parts[1] if len(parts) > 1 else ""
    params: Dict[str, Any] = {}
    if backend_key == "faiss":
        bid = f"faiss:{extra or 'flat'}"
        from .faiss_backend import make_faiss_backend
        inst = make_faiss_backend(extra or "flat")
        return bid, inst, params
    if backend_key == "hnswlib":
        bid = "hnswlib"
        from .hnswlib_backend import make_hnswlib_backend
        inst = make_hnswlib_backend()
        return bid, inst, params
    if backend_key in ("bm25", "tantivy"):
        bid = "bm25:tantivy"
        from .bm25_tantivy_backend import make_bm25_backend
        inst = make_bm25_backend()
        return bid, inst, params
    if backend_key == "hybrid":
        from .hybrid import make_hybrid_backend
        bid = "hybrid"
        inst, params = make_hybrid_backend(extra)
        return bid, inst, params
    # Fallback: exact search with numpy
    from .faiss_backend import make_faiss_backend
    return "faiss:flat", make_faiss_backend("flat"), params

