import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List
import numpy as np
import pandas as pd

from .lattice import edge_hash, build_lattice_spd
from .embeddings import load_model, preset_meta
from .receipts import LatticeReceipt
from .utils import atomic_write_bytes, atomic_write_text, Manifest, canonical_json, append_jsonl, state_sig, apply_determinism_if_enabled

def ingest_dir(
    input_dir: Path,
    out_dir: Path,
    group_by: str = "doc.section",
    dim: int = 32,
    k: int = 4,
    lambda_G: float = 1.0,
    lambda_C: float = 0.5,
    lambda_Q: float = 4.0,
    tol: float = 1e-5,
    max_iter: int = 256,
    embed_model: str = "bge-small-en-v1.5",
    embed_device: str = "cpu",
    embed_batch_size: int = 32,
    embed_strict_hash: bool = False,
) -> List[LatticeReceipt]:
    out_dir.mkdir(parents=True, exist_ok=True)
    groups_root = out_dir/"groups"
    router_root = out_dir/"router"
    receipts_root = out_dir/"receipts"
    router_root.mkdir(parents=True, exist_ok=True)
    receipts_root.mkdir(parents=True, exist_ok=True)

    receipts: List[LatticeReceipt] = []
    centroids: List[np.ndarray] = []
    ids: List[str] = []
    entries: List[dict] = []

    files = sorted([p for p in Path(input_dir).glob("**/*") if p.suffix.lower() in {".txt",".md"}])

    # Simple content dedup map across shards: file_sha256 -> first lattice_id
    dedup_map_path = receipts_root/"dedup_map.jsonl"
    existing_hashes: set[str] = set()
    if dedup_map_path.exists():
        try:
            with dedup_map_path.open("r", encoding="utf-8") as f:
                for ln in f:
                    try:
                        rec = json.loads(ln)
                        if rec.get("file_sha256"):
                            existing_hashes.add(rec["file_sha256"]) 
                    except Exception:
                        continue
        except Exception:
            pass

    # Determinism (opt-in)
    deterministic = apply_determinism_if_enabled()
    # Initialize embedding backend once per ingest
    be = load_model(embed_model, device=embed_device, batch_size=int(embed_batch_size), strict_hash=bool(embed_strict_hash))
    if dim != be.dim:
        # Enforce model/index dimension agreement
        dim = be.dim
    gid = 1
    lid_counter = 1
    for f in files:
        text = f.read_text(encoding="utf-8", errors="ignore")
        file_bytes = text.encode("utf-8")
        file_sha = hashlib.sha256(file_bytes).hexdigest()
        # Dedup: skip re-embedding identical attachments
        if file_sha in existing_hashes:
            # WAL entry for dedup skip
            append_jsonl(receipts_root/"ingest.wal.jsonl", {
                "ts": datetime.now(timezone.utc).isoformat(),
                "event": "dedup_skip",
                "source": str(f.relative_to(input_dir).as_posix()),
                "file_sha256": file_sha,
            })
            continue
        # Simple canonicalization: strip lines, collapse blank lines
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        block, chunk_texts = [], []
        for i, ln in enumerate(lines):
            block.append(ln)
            if len(block) == 6 or i == len(lines) - 1:
                chunk_texts.append(" ".join(block)[:2000])
                block = []
        if not chunk_texts:
            continue
        # Embed chunk texts with doc prompt
        Xemb = be.embed_docs(chunk_texts)
        # Use SPD-based builder for accurate receipts (with precomputed embeddings)
        # Build synthetic chunk objects to provide provenance into receipts
        prov_chunks = [{"text": t, "meta": {"file": f.name}} for t in chunk_texts]
        X, E, U, stats = build_lattice_spd(
            prov_chunks,
            dim=dim,
            k=k,
            lambda_G=lambda_G,
            lambda_C=lambda_C,
            lambda_Q=lambda_Q,
            tol=tol,
            max_iter=max_iter,
            precomputed_X=Xemb,
        )
        eh = stats.get("edge_hash", edge_hash(E))
        dH = float(stats.get("deltaH_total", 0.0))
        group_id = f"G-{gid:06d}"
        lattice_id = f"L-{lid_counter:06d}"
        gid += 1
        lid_counter += 1

        gdir = groups_root / group_id / lattice_id
        gdir.mkdir(parents=True, exist_ok=True)

        atomic_write_bytes(gdir / "embeds.f32", X.astype("float32").tobytes())
        # Also write .npy for explicit shape/dtype and easier mmap
        try:
            import io as _io
            _buf = _io.BytesIO()
            np.save(_buf, X.astype(np.float32, copy=False))
            _npy_bytes = _buf.getvalue()
            atomic_write_bytes(gdir / "embeds.npy", _npy_bytes)
            # Sidecar sha256 for auditability
            try:
                _sha = hashlib.sha256(_npy_bytes).hexdigest()
                atomic_write_text(gdir / "embeds.sha256", _sha + "\n")
            except Exception:
                pass
        except Exception:
            # Non-fatal; retain f32 raw only
            pass
        atomic_write_bytes(gdir / "ustar.f32", U.astype("float32").tobytes())
        atomic_write_bytes(gdir / "edges.bin", np.asarray(E, dtype=np.int32).tobytes())
        # Optional CSR tri-file split for edges (indptr.u64, indices.u32, weights.f32)
        try:
            import os as _os
            if _os.environ.get("LATTICEDB_EDGES_TRIFILE"):
                # Build CSR from undirected edge list E (u,v) with unit weights
                n = int(X.shape[0])
                if E.size > 0 and n > 0:
                    adj = [[] for _ in range(n)]
                    for (u, v) in np.asarray(E, dtype=np.int64):
                        if 0 <= u < n and 0 <= v < n and u != v:
                            adj[u].append(int(v))
                            adj[v].append(int(u))
                    indptr = [0]
                    indices: list[int] = []
                    for nbrs in adj:
                        nbrs.sort()
                        indices.extend(nbrs)
                        indptr.append(len(indices))
                    indptr_arr = np.asarray(indptr, dtype=np.uint64)
                    indices_arr = np.asarray(indices, dtype=np.uint32) if indices else np.zeros((0,), dtype=np.uint32)
                    weights_arr = np.ones((indices_arr.shape[0],), dtype=np.float32)
                    edir = gdir/"edges"
                    edir.mkdir(parents=True, exist_ok=True)
                    atomic_write_bytes(edir/"indptr.u64", indptr_arr.tobytes())
                    atomic_write_bytes(edir/"indices.u32", indices_arr.tobytes())
                    atomic_write_bytes(edir/"weights.f32", weights_arr.tobytes())
                    # Sidecar hash for the tri-file set
                    try:
                        _h = hashlib.sha256()
                        _h.update(indptr_arr.tobytes())
                        _h.update(b"\n")
                        _h.update(indices_arr.tobytes())
                        _h.update(b"\n")
                        _h.update(weights_arr.tobytes())
                        _h.update(b"\n")
                        atomic_write_text(edir/"edges.sha256", _h.hexdigest()+"\n")
                    except Exception:
                        pass
        except Exception:
            # Non-fatal; stick with monolithic edges.bin
            pass
        # Write chunks.parquet in v1.0 schema
        try:
            created_at = datetime.fromtimestamp(f.stat().st_ctime, tz=timezone.utc).isoformat()
        except Exception:
            created_at = datetime.now(timezone.utc).isoformat()
        try:
            modified_at = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).isoformat()
        except Exception:
            modified_at = created_at
        suffix = f.suffix.lower()
        source_type = "md_text" if suffix == ".md" else "txt_text"
        mimetype = "text/markdown" if suffix == ".md" else "text/plain"
        relpath = str(f.relative_to(input_dir).as_posix())
        # Offsets: best-effort over normalized text sequence
        rows = []
        offset = 0
        doc_id = file_sha  # reuse canonicalized file hash for now
        for i, t in enumerate(chunk_texts):
            tsha = hashlib.sha256(t.encode("utf-8")).hexdigest()
            start = offset
            end = start + len(t)
            rows.append({
                "lattice_id": f"{group_id}/{lattice_id}",
                "doc_id": doc_id,
                "chunk_id": f"{doc_id}:{start}",
                "source_type": source_type,
                "mimetype": mimetype,
                "path": relpath,
                "title": None,
                "author": None,
                "created_at": created_at,
                "modified_at": modified_at,
                "page_or_row": int(i),
                "section_title": None,
                "section_level": None,
                "text": t,
                "text_sha256": tsha,
                "ocr_avg_conf": None,
                "ocr_low_conf": None,
                "tags": [],
                "acl_tenants": [],
                "acl_roles": [],
                "model_name": embed_model,
                "model_sha256": "stub-model-sha256",
                "dim": int(dim),
                "file_sha256": file_sha,
                "offset_start": int(start),
                "offset_end": int(end),
            })
            offset = end
        pd.DataFrame(rows).to_parquet(gdir / "chunks.parquet")

        meta = preset_meta(be)
        rec = LatticeReceipt.from_core(
            lattice_id=lattice_id,
            group_id=group_id,
            file_sha256=file_sha,
            edge_hash=eh,
            deltaH_total=float(dH),
            cg_iters=int(stats.get("cg_iters", 0)),
            final_residual=float(stats.get("final_residual", 0.0)),
            dim=int(dim),
            lambda_G=float(lambda_G),
            lambda_C=float(lambda_C),
            lambda_Q=float(lambda_Q),
            embed_model=meta.get("embed_model"),
            embed_dim=meta.get("embed_dim"),
            prompt_format=meta.get("prompt_format"),
            hf_rev=meta.get("hf_rev"),
            model_sha256=meta.get("weights_sha256") or "stub-model-sha256",
            tokenizer_sha256=meta.get("tokenizer_sha256"),
            device=meta.get("device"),
            batch_size=meta.get("batch_size"),
            pooling=meta.get("pooling"),
            strict_hash=meta.get("strict_hash"),
            deterministic=bool(deterministic),
        )
        atomic_write_text(gdir / "receipt.json", rec.model_dump_json(indent=2))
        # Update dedup map and WAL
        try:
            append_jsonl(dedup_map_path, {"file_sha256": file_sha, "lattice_id": lattice_id, "source": str(f.relative_to(input_dir).as_posix())})
        except Exception:
            pass
        append_jsonl(receipts_root/"ingest.wal.jsonl", {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": "ingest_ok",
            "lattice_id": lattice_id,
            "group_id": group_id,
            "file_sha256": file_sha,
            "chunks": len(chunk_texts),
        })
        receipts.append(rec)
        centroids.append(U.mean(axis=0))
        ids.append(lattice_id)
        # Collect manifest entry for this lattice
        entries.append(
            {
                "group_id": group_id,
                "lattice_id": lattice_id,
                "edge_hash": eh,
                "deltaH_total": float(dH),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "source_file": f.name,
                "source_relpath": str(f.relative_to(input_dir).as_posix()),
                "chunk_count": len(chunk_texts),
                "file_bytes": len(file_bytes),
                "file_sha256": rec.file_sha256,
                "embed_model": meta.get("embed_model"),
                "embed_dim": int(dim),
            }
        )

    if centroids:
        C = np.stack(centroids, axis=0).astype("float32")
        # Write raw f32 for backward-compat
        atomic_write_bytes(router_root/"centroids.f32", C.tobytes())
        # Also write .npy for explicit shape/dtype
        try:
            import io as _io
            buf = _io.BytesIO()
            # Save as float32 explicitly
            np.save(buf, C.astype(np.float32, copy=False))
            atomic_write_bytes(router_root/"centroids.npy", buf.getvalue())
        except Exception:
            # Non-fatal fallback
            pass
        # Atomic write for router meta parquet
        import io
        buf = io.BytesIO()
        pd.DataFrame({"lattice_id": ids}).to_parquet(buf)
        atomic_write_bytes(router_root/"meta.parquet", buf.getvalue())

        # Write router receipt with centroid sha256 and minimal params
        try:
            cent_bytes = (router_root/"centroids.f32").read_bytes()
            centroid_sha256 = hashlib.sha256(cent_bytes).hexdigest()
        except Exception:
            centroid_sha256 = ""
        router_receipt = {
            "version": "1",
            "centroid_sha256": centroid_sha256,
            "L": int(C.shape[0]),
            "D": int(C.shape[1]) if C.ndim == 2 else int(C.size),
            "build": {"source": "ingest_dir", "time": datetime.now(timezone.utc).isoformat()},
        }
        # Compute state_sig over content (excluding state_sig itself)
        rsig = state_sig({k: v for k, v in router_receipt.items() if k != "state_sig"})
        router_receipt["state_sig"] = rsig
        atomic_write_text(router_root/"receipt.json", json.dumps(router_receipt, indent=2))

        # Update manifest with new lattices
        man = Manifest(out_dir)
        if entries:
            man.append(entries)
        # Write normalized config used for db root (provenance)
        config = {
            "version": "1",
            "group_by": group_by,
            "dim": int(dim),
            "k": int(k),
            "lambda_G": float(lambda_G),
            "lambda_C": float(lambda_C),
            "lambda_Q": float(lambda_Q),
            "tol": float(tol),
            "max_iter": int(max_iter),
            # Embedding provenance
            **meta,
        }
        atomic_write_text(receipts_root/"config.json", canonical_json(config))
        # Ensure SCHEMA_VERSION exists at root
        try:
            atomic_write_text(out_dir/"SCHEMA_VERSION", "1\n")
        except Exception:
            pass
    return receipts