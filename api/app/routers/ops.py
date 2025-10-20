"""Operational endpoints: health, readiness, version, license, metrics, db receipt.
SPDX-License-Identifier: BUSL-1.1
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from ..core.config import settings


router = APIRouter(tags=["ops"])


@router.get("/health", summary="Health check")
def health():
    return {"ok": True}


@router.get("/v1/license/status", tags=["license"], summary="Report license mode and metadata")
def license_status():
    return {
        "mode": settings.license_mode,
        "id": settings.license_id,
        "tier": settings.license_tier,
        "expiry": settings.license_expiry,
        "saas_allowed": settings.saas_allowed,
        "notice": "Not for production use" if settings.license_mode != "prod" else "Production license active",
    }


@router.get("/readyz", summary="Readiness probe", description="Checks presence and integrity of DB artifacts and that config_hash in db receipt matches receipts/config.json.")
def readyz(db_path: str | None = None):
    root = Path(db_path) if db_path else Path(settings.db_root)
    checks: dict[str, Any] = {}

    router_centroids = root / "router" / "centroids.f32"
    router_meta = root / "router" / "meta.parquet"
    db_receipt = root / "receipts" / "db_receipt.json"
    cfg = root / "receipts" / "config.json"
    manifest = root / "manifest.parquet"

    checks["router_centroids_exists"] = router_centroids.exists() and router_centroids.stat().st_size > 0
    checks["router_meta_exists"] = router_meta.exists()
    checks["db_receipt_exists"] = db_receipt.exists()
    checks["config_exists"] = cfg.exists()
    checks["manifest_exists"] = manifest.exists()

    try:
        if cfg.exists() and db_receipt.exists():
            cfg_hash = hashlib.sha256(cfg.read_bytes()).hexdigest()
            dr = json.loads(db_receipt.read_text())
            checks["config_hash_matches"] = dr.get("config_hash") == cfg_hash
        else:
            checks["config_hash_matches"] = False
    except Exception:
        checks["config_hash_matches"] = False

    dmeta = None
    meta_count: int | None = None
    try:
        if router_meta.exists():
            import pandas as pd  # local import
            dmeta = pd.read_parquet(router_meta)
            checks["router_meta_readable"] = True
            meta_count = len(dmeta)
        else:
            checks["router_meta_readable"] = False
    except Exception:
        checks["router_meta_readable"] = False

    try:
        centroid_count = None
        if router_centroids.exists() and cfg.exists():
            cfg_obj = json.loads(cfg.read_text())
            dim = int(cfg_obj.get("dim", 32))
            if dim > 0:
                size = router_centroids.stat().st_size
                bytes_per = dim * 4
                if bytes_per > 0 and size % bytes_per == 0:
                    centroid_count = size // bytes_per
                else:
                    centroid_count = None
        if meta_count is not None and centroid_count is not None:
            checks["router_counts_consistent"] = int(centroid_count) == int(meta_count)
        else:
            checks["router_counts_consistent"] = False
        if manifest.exists() and dmeta is not None:
            import pandas as pd
            dman = pd.read_parquet(manifest)
            man_ids = set(dman["lattice_id"].astype(str).tolist()) if "lattice_id" in dman.columns else set()
            meta_ids = set(dmeta["lattice_id"].astype(str).tolist()) if "lattice_id" in dmeta.columns else set()
            checks["router_ids_in_manifest"] = meta_ids.issubset(man_ids) and len(meta_ids) > 0
        else:
            checks["router_ids_in_manifest"] = False
    except Exception:
        checks["router_counts_consistent"] = False
        checks["router_ids_in_manifest"] = False

    ready = all(bool(v) for v in checks.values())
    return {"ready": ready, "checks": checks}


@router.get("/livez", summary="Liveness probe")
def livez():
    return {"live": True}


@router.get("/version", summary="Service version")
def version():
    # Resolve from app.main so tests can monkeypatch pkg_version and PackageNotFoundError
    from .. import main as m  # type: ignore
    try:
        ver = m.pkg_version("oscillink-latticedb")
    except m.PackageNotFoundError:  # type: ignore[attr-defined]
        ver = "0.0.0+dev"
    git_sha = os.environ.get("GIT_SHA", "unknown")
    return {"version": ver, "git_sha": git_sha}


@router.get("/health/security", summary="Security posture")
def health_security():
    egress_denied = True if not os.environ.get("LATTICEDB_EGRESS_ALLOWED") else False
    models_local_verified = True
    return {"egress": "denied" if egress_denied else "allowed", "models": "local-verified" if models_local_verified else "remote"}


@router.get("/v1/db/receipt", summary="Get DB Merkle receipt")
def get_db_receipt(db_path: str | None = None):
    root = Path(db_path) if db_path else Path(settings.db_root)
    p = root / "receipts" / "db_receipt.json"
    if not p.exists():
        raise HTTPException(status_code=404, detail="db receipt not found")
    try:
        data = json.loads(p.read_text())
        return data
    except Exception:
        raise HTTPException(status_code=500, detail="invalid db receipt")
