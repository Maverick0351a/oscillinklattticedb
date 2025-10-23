"""BM25 (Tantivy) retrieval backend (optional).
SPDX-License-Identifier: BUSL-1.1

This adapter is a placeholder: it returns no results unless the corpus and tantivy binding
are available. It still produces deterministic build receipts and can be used in hybrid mode.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
import json
from pathlib import Path

from .base import RetrievalBackend, Candidate, BuildReceipt, dir_tree_sha256, _get_safe_base, canonicalize_and_validate
from ..utils import atomic_write_text  # type: ignore


class _TantivyBM25Backend:
    def __init__(self) -> None:
        self._ok = False
        try:
            import tantivy  # type: ignore  # noqa: F401
            self._ok = True
        except Exception:
            self._ok = False
        self._index_dir: Optional[Path] = None

    def build(self, vectors_or_docs_path: str, out_dir: str, **kwargs: Any) -> BuildReceipt:
        # In scaffold mode we don't actually build; just hash any existing folder
        base = _get_safe_base()
        outp = canonicalize_and_validate(out_dir, base)
        if outp is None:
            # Do not write outside base; return deterministic stub
            return BuildReceipt(
                backend_id="bm25:tantivy",
                backend_version="tantivy-py" if self._ok else "stub",
                params={"schema": "default"},
                index_hash=_hash_stub(),
                training_hash=None,
            )
        outp.mkdir(parents=True, exist_ok=True)
        # Write a tiny marker for hashing deterministically
        (outp/"bm25.marker").write_text("bm25:tantivy")
        index_hash = dir_tree_sha256(outp)
        self._index_dir = outp
        br = BuildReceipt(
            backend_id="bm25:tantivy",
            backend_version="tantivy-py" if self._ok else "stub",
            params={"schema": "default"},
            index_hash=index_hash,
            training_hash=None,
        )
        try:
            atomic_write_text(outp/"index_receipt.json", json.dumps({
                "version": 1,
                "backend_id": br["backend_id"],
                "backend_version": br["backend_version"],
                "params": br["params"],
                "index_hash": br["index_hash"],
                "training_hash": br["training_hash"],
            }, indent=2))
        except Exception:
            pass
        return br

    def query(self, qvec, k: int, filters: Optional[Dict[str, Any]] = None) -> List[Candidate]:  # noqa: ANN001
        # Vector is ignored; real implementation would use string query.
        return []

    def info(self) -> Dict[str, Any]:
        return {"backend": "bm25:tantivy", "available": self._ok}


def make_bm25_backend() -> RetrievalBackend:
    return _TantivyBM25Backend()


def _hash_stub() -> str:
    import hashlib as _h
    return _h.sha256(b"no-write").hexdigest()

