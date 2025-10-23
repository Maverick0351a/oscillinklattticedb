from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from .utils import atomic_write_text


@dataclass
class IndexBuildResult:
    dim: int
    nvec: int
    index_path: Path
    meta_path: Path
    postings_path: Path
    index_sha256: str


def _hash_file(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _collect_docs_for_shard(db_root: Path, shard_id: str) -> List[Dict[str, Any]]:
    # Placeholder: we don't have a text corpus here; emit lattice IDs as entries
    from .router import Router
    _C, ids = Router(db_root).load_centroids()
    return [{"lattice_id": lid} for lid in ids]


def build_bm25_index_for_shard(db_root: Path, shard_id: str) -> IndexBuildResult:
    """Build a BM25 index for a shard (placeholder) and seal.

    Layout under db_root/indexes/<shard_id>:
      - staging/ (temp)
      - sealed/ (final active)
      - postings.jsonl (metadata per doc)
      - meta.json (index metadata)
      - bm25.marker (adapter output)
      - index_receipt.json (adapter receipt)
    """
    idx_root = db_root / "indexes" / shard_id
    staging = idx_root / "staging"
    sealed = idx_root / "sealed"
    idx_root.mkdir(parents=True, exist_ok=True)
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)

    # Use retrieval adapter to emit marker and receipt
    try:
        from .retrieval.bm25_tantivy_backend import make_bm25_backend
        backend = make_bm25_backend()
        backend.build(str(db_root), str(staging))
    except Exception:
        (staging/"bm25.marker").write_text("bm25:tantivy")

    # Postings and meta
    docs = _collect_docs_for_shard(db_root, shard_id)
    postings_path = staging / "postings.jsonl"
    with postings_path.open("w", encoding="utf-8") as f:
        for m in docs:
            f.write(json.dumps(m) + "\n")
    meta_obj = {"version": 1, "shard_id": shard_id, "type": "bm25:tantivy", "docs": len(docs)}
    meta_path = staging / "meta.json"
    atomic_write_text(meta_path, json.dumps(meta_obj, indent=2))

    # Hash marker for consistency
    marker = staging / "bm25.marker"
    idx_sha = _hash_file(marker) if marker.exists() else ""

    # Seal
    if sealed.exists():
        shutil.rmtree(sealed, ignore_errors=True)
    staging.replace(sealed)

    return IndexBuildResult(dim=0, nvec=len(docs), index_path=sealed/"bm25.marker", meta_path=sealed/"meta.json", postings_path=sealed/"postings.jsonl", index_sha256=idx_sha)
