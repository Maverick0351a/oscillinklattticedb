"""Deterministic hybrid retrieval: combine vector and BM25 scores.
SPDX-License-Identifier: BUSL-1.1
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple, cast

from .base import RetrievalBackend, Candidate, resolve_backend


class _HybridBackend:
    def __init__(self, vec: RetrievalBackend, bm25: RetrievalBackend, w_vec: float, w_lex: float) -> None:
        self.vec = vec
        self.bm25 = bm25
        self.w_vec = float(w_vec)
        self.w_lex = float(w_lex)

    def build(self, vectors_or_docs_path: str, out_dir: str, **kwargs: Any):  # noqa: ANN001
        r1 = self.vec.build(vectors_or_docs_path, out_dir + "/vec", **kwargs)
        _ = self.bm25.build(vectors_or_docs_path, out_dir + "/bm25", **kwargs)
        # Roll-up receipt
        # Return a BuildReceipt-compatible dict
        return {
            "backend_id": "hybrid",
            "backend_version": "1",
            "params": {"weights": {"vec": self.w_vec, "lex": self.w_lex}},
            "index_hash": r1["index_hash"],
            "training_hash": r1.get("training_hash"),
        }

    def _normalize(self, scores: List[float]) -> List[float]:
        if not scores:
            return []
        # z by rank: highest gets 1.0, lowest 0.0
        n = len(scores)
        order = sorted(range(n), key=lambda i: -scores[i])
        z = [0.0] * n
        for rank, i in enumerate(order):
            z[i] = 1.0 - (rank / max(1, n - 1)) if n > 1 else 1.0
        return z

    def query(self, qvec, k: int, filters=None):  # noqa: ANN001
        vres = self.vec.query(qvec, k)
        lres = self.bm25.query(qvec, k)
        # merge by id
        ids = {c["id"] for c in vres} | {c["id"] for c in lres}
        vidx = {c["id"]: c for c in vres}
        lidx = {c["id"]: c for c in lres}
        vnorm = self._normalize([vidx[i]["score"] for i in vidx])
        # Map normalized vector scores back to ids deterministically
        vmap = {i: vnorm[j] for j, i in enumerate(sorted(vidx, key=lambda x: (-vidx[x]["score"], x)))}
        # Lexical has empty scores in the stub; keep 0.0
        out: List[Candidate] = []
        for lid in sorted(ids):
            sv = float(vmap.get(lid, 0.0))
            sl = float(lidx.get(lid, {}).get("score", 0.0))
            score = self.w_vec * sv + self.w_lex * sl
            out.append({"id": lid, "score": score, "meta": {"sv": sv, "sl": sl}})
        out.sort(key=lambda c: (-c["score"], c["id"]))
        return out[: int(max(1, k))]

    def info(self) -> Dict[str, Any]:
        return {"backend": "hybrid", "weights": {"vec": self.w_vec, "lex": self.w_lex}}


def make_hybrid_backend(spec: str) -> Tuple[RetrievalBackend, Dict[str, Any]]:
    # Parse spec like "0.7vec,0.3bm25" or "vec=0.7,lex=0.3"
    w_vec = 0.7
    w_lex = 0.3
    if spec:
        parts = [p.strip() for p in spec.split(",") if p.strip()]
        for p in parts:
            if p.endswith("vec") and ":" not in p:
                try:
                    w_vec = float(p[:-3])
                except Exception:
                    pass
            elif p.endswith("bm25") and ":" not in p:
                try:
                    w_lex = float(p[:-4])
                except Exception:
                    pass
            elif "vec=" in p:
                try:
                    w_vec = float(p.split("=", 1)[1])
                except Exception:
                    pass
            elif "lex=" in p:
                try:
                    w_lex = float(p.split("=", 1)[1])
                except Exception:
                    pass
    # Instantiate defaults
    _, vec, _ = resolve_backend("faiss:flat")
    _, bm25, _ = resolve_backend("bm25")
    inst: RetrievalBackend = cast(RetrievalBackend, _HybridBackend(vec, bm25, w_vec, w_lex))
    return inst, {"weights": {"vec": w_vec, "lex": w_lex}}

