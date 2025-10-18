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
from .utils import atomic_write_bytes, atomic_write_text, Manifest, canonical_json, append_jsonl

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
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        block, chunks = [], []
        for i, ln in enumerate(lines):
            block.append(ln)
            if len(block) == 6 or i == len(lines) - 1:
                chunks.append({"text": " ".join(block)[:2000], "meta": {"file": f.name}})
                block = []
        if not chunks:
            continue
        # Embed chunk texts with doc prompt
        texts = [c["text"] for c in chunks]
        Xemb = be.embed_docs(texts)
        # Use SPD-based builder for accurate receipts (with precomputed embeddings)
        X, E, U, stats = build_lattice_spd(
            chunks,
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
        atomic_write_bytes(gdir / "ustar.f32", U.astype("float32").tobytes())
        atomic_write_bytes(gdir / "edges.bin", np.asarray(E, dtype=np.int32).tobytes())
        pd.DataFrame(chunks).to_parquet(gdir / "chunks.parquet")

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
            "chunks": len(chunks),
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
                "chunk_count": len(chunks),
                "file_bytes": len(file_bytes),
                "file_sha256": rec.file_sha256,
            }
        )

    if centroids:
        C = np.stack(centroids, axis=0).astype("float32")
        atomic_write_bytes(router_root/"centroids.f32", C.tobytes())
        # Atomic write for router meta parquet
        import io
        buf = io.BytesIO()
        pd.DataFrame({"lattice_id": ids}).to_parquet(buf)
        atomic_write_bytes(router_root/"meta.parquet", buf.getvalue())

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
    return receipts