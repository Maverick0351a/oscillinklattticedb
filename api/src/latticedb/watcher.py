from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .ingest import ingest_dir
from .merkle import merkle_root
from .shards import write_shards_yaml, apply_backend_promotions
from .router import Router
from .composite import composite_settle
from .receipts import CompositeReceipt, ShardReceipt
from .index_faiss import build_faiss_index_for_shard


def single_scan(
    input_root: Path,
    db_root: Path,
    *,
    embed_model: str = "bge-small-en-v1.5",
    embed_device: str = "cpu",
    embed_batch_size: int = 32,
    embed_strict_hash: bool = False,
    firm_path: Path | None = None,
) -> dict[str, Any]:
    # 1) Write/update shards.yaml (by top-level folder)
    shards_yaml = db_root / "receipts" / "shards.yaml"
    shards_state = write_shards_yaml(input_root, shards_yaml)

    # 1b) Optionally read firm.yaml for backend switching thresholds
    firm_cfg: dict[str, Any] = {}
    if firm_path is None:
        # Try project root firm.yaml (one level up from api/ typical layout)
        # Search upwards from db_root
        cur = db_root.resolve()
        for _ in range(3):
            candidate = cur / "firm.yaml"
            if candidate.exists():
                firm_path = candidate
                break
            if cur.parent == cur:
                break
            cur = cur.parent
    if firm_path and Path(firm_path).exists():
        try:
            import yaml  # type: ignore
            firm_cfg = yaml.safe_load(Path(firm_path).read_text(encoding="utf-8")) or {}
        except Exception:
            firm_cfg = {}

    # 2) Ingest all text under input_root into db_root
    receipts = ingest_dir(
        input_root,
        db_root,
        embed_model=embed_model,
        embed_device=embed_device,
        embed_batch_size=int(embed_batch_size),
        embed_strict_hash=bool(embed_strict_hash),
    )

    # 3) Recompute composite over all centroids (always-on)
    C, ids = Router(db_root).load_centroids()
    sel = list(range(len(ids)))
    # Load SPD params from config.json if present
    k = 4
    lamG = 1.0
    lamC = 0.5
    lamQ = 4.0
    tol = 1e-5
    max_iter = 256
    cfg_path = db_root / "receipts" / "config.json"
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text())
            k = int(cfg.get("k", k))
            lamG = float(cfg.get("lambda_G", lamG))
            lamC = float(cfg.get("lambda_C", lamC))
            lamQ = float(cfg.get("lambda_Q", lamQ))
            tol = float(cfg.get("tol", tol))
            max_iter = int(cfg.get("max_iter", max_iter))
        except Exception:
            pass
    dH, iters, resid, ehash = composite_settle(C, sel, k=k, lambda_G=lamG, lambda_C=lamC, lambda_Q=lamQ, tol=tol, max_iter=max_iter)

    # DB config hash and merkle leaves
    if cfg_path.exists():
        config_hash = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
    else:
        config_hash = hashlib.sha256(b"stub-config").hexdigest()
    # Optional: Determine backend promotions based on firm thresholds
    promotions: dict[str, str] = {}
    backend_cfg = (firm_cfg.get("backend_switch") or {}) if isinstance(firm_cfg, dict) else {}
    if backend_cfg.get("enable"):
        th = backend_cfg.get("thresholds") or {}
        max_mb = float(th.get("size_mb", 1e12))
        max_chunks = int(th.get("chunks", 1 << 62))
        target_backend = str(backend_cfg.get("target", "faiss"))
        # Read manifest to count chunks per shard
        # Map lattice file sources to shard by path prefix
        manifest_path = db_root / "manifest.parquet"
        chunk_counts: dict[str, int] = {}
        if manifest_path.exists():
            try:
                import pandas as pd  # type: ignore
                pd.read_parquet(manifest_path)
                # Best-effort mapping: if source_file path is stored, but we only saved filename
                # so fall back to using file_count from shard entry.
                for s in shards_state.shards:
                    chunk_counts[s.id] = int(s.file_count)  # proxy
            except Exception:
                for s in shards_state.shards:
                    chunk_counts[s.id] = int(s.file_count)
        else:
            for s in shards_state.shards:
                chunk_counts[s.id] = int(s.file_count)
        for s in shards_state.shards:
            size_mb = (s.size_bytes or 0) / (1024 * 1024)
            chunks = chunk_counts.get(s.id, 0)
            if s.active_backend == "jsonl" and (size_mb >= max_mb or chunks >= max_chunks):
                promotions[s.id] = target_backend
    # Apply promotions if any
    if promotions:
        shards_state = apply_backend_promotions(shards_yaml, promotions)

    # Cleanup any stale staging dirs from prior crashes
    idx_root = db_root / "indexes"
    if idx_root.exists():
        # best-effort cleanup of leftover staging under each shard dir
        for sd in idx_root.iterdir():
            stg = sd / "staging"
            if stg.exists():
                import shutil
                shutil.rmtree(stg, ignore_errors=True)

    # Build shard receipts and include them in Merkle leaves
    shard_receipts: list[ShardReceipt] = []
    shards_dir = db_root / "receipts" / "shards"
    shards_dir.mkdir(parents=True, exist_ok=True)
    for s in shards_state.shards:
        sealed = None
        index_meta = None
        index_sha = None
        # If backend is faiss, make sure a sealed index exists
        if s.active_backend == "faiss":
            try:
                res = build_faiss_index_for_shard(db_root, s.id)
                sealed = True
                index_meta = {"dim": res.dim, "nvec": res.nvec, "type": "flat_l2"}
                index_sha = res.index_sha256
            except Exception:
                sealed = False
        sr = ShardReceipt.build(
            shard_id=s.id,
            path=s.path,
            size_bytes=int(s.size_bytes),
            file_count=int(s.file_count),
            active_backend=s.active_backend,
            centroid_hash=s.centroid_hash,
            sealed=sealed,
            index_meta=index_meta,
            index_sha256=index_sha,
        )
        shard_receipts.append(sr)
        (shards_dir / f"{s.id}.receipt.json").write_text(sr.model_dump_json(indent=2))
    # Merkle leaves will be computed after composite is built

    # 4) Write composite receipt and db receipt
    comp = CompositeReceipt.build(
        db_root="",
        lattice_ids=ids,
        edge_hash_composite=ehash,
        deltaH_total=float(dH),
        cg_iters=int(iters),
        final_residual=float(resid),
        epsilon=1e-3,
        tau=0.30,
        filters={},
    )
    # Recompute DB root over composite + shards + config
    leaves_with_comp = [comp.state_sig, *[sr.state_sig for sr in shard_receipts], config_hash]
    root = merkle_root(leaves_with_comp)
    # Update comp.db_root to the newly computed root
    comp.db_root = root
    (db_root / "receipts").mkdir(parents=True, exist_ok=True)
    (db_root / "receipts" / "composite.receipt.json").write_text(comp.model_dump_json(indent=2))
    (db_root / "receipts" / "db_receipt.json").write_text(
        json.dumps({"version": "1", "db_root": root, "config_hash": config_hash, "leaves": leaves_with_comp}, indent=2)
    )
    return {"count": len(receipts), "db_root": root, "composite": comp.model_dump()}


def watch_loop(
    input_root: Path,
    db_root: Path,
    *,
    interval_secs: int = 30,
    embed_model: str = "bge-small-en-v1.5",
    embed_device: str = "cpu",
    embed_batch_size: int = 32,
    embed_strict_hash: bool = False,
    firm_path: Path | None = None,
) -> None:
    """Continuous watcher loop that periodically runs single_scan with crash-safe index staging cleanup."""
    import time
    while True:
        try:
            single_scan(
                input_root=input_root,
                db_root=db_root,
                embed_model=embed_model,
                embed_device=embed_device,
                embed_batch_size=embed_batch_size,
                embed_strict_hash=embed_strict_hash,
                firm_path=firm_path,
            )
        except Exception:
            # swallow and continue; logs could be added later
            pass
        time.sleep(max(1, int(interval_secs)))
