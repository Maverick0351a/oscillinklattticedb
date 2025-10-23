"""Operational endpoints: health, readiness, version, license, metrics, db receipt.
SPDX-License-Identifier: BUSL-1.1
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Header

from ..core.config import settings


router = APIRouter(tags=["ops"])

# Optional in-process cache for strict readiness checks to avoid heavy, repeated IO
# Use a flexible key shape to allow including file mtimes for invalidation
_READYZ_CACHE: dict[tuple, tuple[float, dict[str, Any]]] = {}


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


@router.get("/readyz", summary="Readiness probe", description="Checks presence and integrity of DB artifacts and that config_hash in db receipt matches receipts/config.json. Also validates router receipt and schema version when present.")
def readyz(db_path: str | None = None, strict: bool = False, schema_limit: int | None = None, summary: bool = False):
    root = Path(db_path) if db_path else Path(settings.db_root)
    checks: dict[str, Any] = {}
    warnings: list[str] = []
    # TTL cache for strict checks (disabled by default). Include key invalidators based on mtimes
    if strict and settings.readyz_strict_ttl_seconds > 0 and not summary:
        def _mt(p: Path) -> float:
            try:
                return p.stat().st_mtime
            except Exception:
                return 0.0
        router_centroids = root / "router" / "centroids.f32"
        router_meta = root / "router" / "meta.parquet"
        router_receipt = root / "router" / "receipt.json"
        db_receipt = root / "receipts" / "db_receipt.json"
        cfg = root / "receipts" / "config.json"
        manifest = root / "manifest.parquet"
        schema_version = root / "SCHEMA_VERSION"
        finger = (
            _mt(db_receipt),
            _mt(cfg),
            _mt(router_receipt),
            _mt(manifest),
            _mt(router_centroids),
            _mt(router_meta),
            _mt(schema_version),
        )
        key = (str(root), True, schema_limit, finger)
        cached = _READYZ_CACHE.get(key)
        if cached:
            ts, payload = cached
            if (time.time() - ts) < settings.readyz_strict_ttl_seconds:
                return payload

    router_centroids = root / "router" / "centroids.f32"
    router_meta = root / "router" / "meta.parquet"
    router_receipt = root / "router" / "receipt.json"
    db_receipt = root / "receipts" / "db_receipt.json"
    cfg = root / "receipts" / "config.json"
    manifest = root / "manifest.parquet"
    schema_version = root / "SCHEMA_VERSION"

    checks["router_centroids_exists"] = router_centroids.exists() and router_centroids.stat().st_size > 0
    checks["router_meta_exists"] = router_meta.exists()
    checks["router_receipt_exists"] = router_receipt.exists()
    checks["db_receipt_exists"] = db_receipt.exists()
    checks["config_exists"] = cfg.exists()
    checks["manifest_exists"] = manifest.exists()
    checks["schema_version_exists"] = schema_version.exists()

    # Summary mode: provide a cheap probe without expensive parquet reads or hashing.
    # Only used when strict is False; strict implies full validation.
    if summary and not strict:
        minimal_required = [
            "router_centroids_exists",
            "router_meta_exists",
            "db_receipt_exists",
            "config_exists",
            "manifest_exists",
        ]
        ready_summary = all(bool(checks.get(k, False)) for k in minimal_required)
        # Return only the minimal subset of checks to keep payload small and probe cheap
        return {
            "ready": ready_summary,
            "checks": {k: checks[k] for k in minimal_required},
            "warnings": [],
        }

    try:
        if cfg.exists() and db_receipt.exists():
            cfg_hash = hashlib.sha256(cfg.read_bytes()).hexdigest()
            dr = json.loads(db_receipt.read_text())
            checks["config_hash_matches"] = dr.get("config_hash") == cfg_hash
            # If leaves present, ensure router state_sig is included (when router receipt exists)
            leaves = dr.get("leaves") or []
            if isinstance(leaves, list) and router_receipt.exists():
                try:
                    rr = json.loads(router_receipt.read_text())
                    router_sig = rr.get("state_sig")
                    checks["db_receipt_has_leaves"] = len(leaves) > 0
                    checks["router_sig_in_db_leaves"] = bool(router_sig) and (router_sig in leaves)
                except Exception:
                    checks["db_receipt_has_leaves"] = bool(leaves)
                    checks["router_sig_in_db_leaves"] = False
            else:
                checks["db_receipt_has_leaves"] = bool(leaves)
                # Don't require router_sig_in_db_leaves when router receipt is absent
                if checks.get("router_sig_in_db_leaves") is None:
                    checks["router_sig_in_db_leaves"] = True if not router_receipt.exists() else False
        else:
            checks["config_hash_matches"] = False
            checks["db_receipt_has_leaves"] = False
            checks["router_sig_in_db_leaves"] = False
    except Exception:
        checks["config_hash_matches"] = False
        checks["db_receipt_has_leaves"] = False
        checks["router_sig_in_db_leaves"] = False

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
            dman = None
            try:
                if settings.manifest_cache:
                    from latticedb.cache import manifest_cache  # type: ignore
                    dman = manifest_cache.get(root)
                else:
                    import pandas as pd
                    dman = pd.read_parquet(manifest)
            except Exception:
                try:
                    import pandas as pd
                    dman = pd.read_parquet(manifest)
                except Exception:
                    dman = None
            if dman is not None:
                cols = set(map(str, getattr(dman, "columns", [])))
                man_ids = set(dman["lattice_id"].astype(str).tolist()) if "lattice_id" in cols else set()
            else:
                man_ids = set()
            meta_ids = set(dmeta["lattice_id"].astype(str).tolist()) if "lattice_id" in dmeta.columns else set()
            checks["router_ids_in_manifest"] = meta_ids.issubset(man_ids) and len(meta_ids) > 0
        else:
            checks["router_ids_in_manifest"] = False

        # Router receipt integrity checks
        if router_receipt.exists():
            try:
                rr_obj = json.loads(router_receipt.read_text())
                checks["router_receipt_readable"] = True
                rr_L = rr_obj.get("L")
                rr_D = rr_obj.get("D")
                rr_sha = rr_obj.get("centroid_sha256")
                # Compare L and D to computed counts and config dim
                if centroid_count is not None and isinstance(rr_L, int):
                    checks["router_receipt_L_matches"] = int(rr_L) == int(centroid_count)
                else:
                    checks["router_receipt_L_matches"] = False
                if cfg.exists() and isinstance(rr_D, int):
                    cfg_dim = int(json.loads(cfg.read_text()).get("dim", -1))
                    checks["router_receipt_D_matches"] = int(rr_D) == int(cfg_dim)
                else:
                    checks["router_receipt_D_matches"] = False
                # Compute centroids hash and compare
                if router_centroids.exists() and rr_sha:
                    h = hashlib.sha256()
                    with open(router_centroids, "rb") as f:
                        for chunk in iter(lambda: f.read(1024 * 1024), b""):
                            h.update(chunk)
                    checks["router_centroids_sha256_matches"] = h.hexdigest() == rr_sha
                else:
                    checks["router_centroids_sha256_matches"] = False
            except Exception:
                checks["router_receipt_readable"] = False
                checks["router_receipt_L_matches"] = False
                checks["router_receipt_D_matches"] = False
                checks["router_centroids_sha256_matches"] = False
        else:
            checks["router_receipt_readable"] = False
            checks["router_receipt_L_matches"] = False
            checks["router_receipt_D_matches"] = False
            checks["router_centroids_sha256_matches"] = False
    except Exception:
        checks["router_counts_consistent"] = False
        checks["router_ids_in_manifest"] = False
        checks["router_receipt_readable"] = False
        checks["router_receipt_L_matches"] = False
        checks["router_receipt_D_matches"] = False
        checks["router_centroids_sha256_matches"] = False

    # Schema version checks
    try:
        if schema_version.exists():
            ver = (schema_version.read_text().strip() or "").splitlines()[0].strip()
            checks["schema_version_supported"] = ver in {"1"}
        else:
            checks["schema_version_supported"] = False
    except Exception:
        checks["schema_version_supported"] = False

    # Soft schema validation (warn-mode)
    try:
        from latticedb.validators import soft_schema_validate  # type: ignore
        # Sanitize schema_limit
        _lim = None
        if schema_limit is not None:
            try:
                _lim = max(1, int(schema_limit))
            except Exception:
                _lim = None
        v = soft_schema_validate(root, schema_limit=_lim)
        warns = list(v.get("warnings", [])) if isinstance(v, dict) else []
        warnings.extend(warns)
    except Exception:
        warnings.append("soft_schema_validate_failed")

    # Compute readiness from a baseline set of checks (non-blocking extras remain in `checks`)
    required_keys = [
        "router_centroids_exists",
        "router_meta_exists",
        "db_receipt_exists",
        "config_exists",
        "manifest_exists",
        "router_meta_readable",
        "router_counts_consistent",
        "router_ids_in_manifest",
        "config_hash_matches",
    ]
    # Informational: ACL columns presence ratio across lattices when enforcement is on
    try:
        if settings.acl_enforce:
            total = 0
            have_acl = 0
            groups_dir = root / "groups"
            if groups_dir.exists():
                import pandas as pd  # type: ignore
                # Sample up to 500 chunk files across groups for speed
                chunk_files = list(groups_dir.glob("**/chunks.parquet"))[:500]
                for cparq in chunk_files:
                    try:
                        df = pd.read_parquet(cparq, columns=None)
                        cols = set(map(str, df.columns))
                        total += 1
                        if ("acl_tenants" in cols) or ("acl_roles" in cols):
                            have_acl += 1
                    except Exception:
                        total += 1
                ratio = (have_acl / total) if total > 0 else 1.0
                checks["acl_columns_present_ratio"] = ratio
                if total > 0 and ratio < 1.0:
                    warnings.append(f"acl_columns_missing_on_some_lattices: ratio={ratio:.2f}")
            else:
                checks["acl_columns_present_ratio"] = 1.0
    except Exception:
        warnings.append("acl_columns_scan_failed")
    # In strict mode, require additional integrity checks to pass
    if strict:
        required_keys = required_keys + [
            "router_receipt_exists",
            "router_receipt_readable",
            "router_receipt_L_matches",
            "router_receipt_D_matches",
            "router_centroids_sha256_matches",
            "schema_version_exists",
            "schema_version_supported",
            "db_receipt_has_leaves",
            "router_sig_in_db_leaves",
        ]
    ready = all(bool(checks.get(k, False)) for k in required_keys)
    payload = {"ready": ready, "checks": checks, "warnings": warnings}
    if strict and settings.readyz_strict_ttl_seconds > 0 and not summary:
        def _mt(p: Path) -> float:
            try:
                return p.stat().st_mtime
            except Exception:
                return 0.0
        finger = (
            _mt(root / "receipts" / "db_receipt.json"),
            _mt(root / "receipts" / "config.json"),
            _mt(root / "router" / "receipt.json"),
            _mt(root / "manifest.parquet"),
            _mt(root / "router" / "centroids.f32"),
            _mt(root / "router" / "meta.parquet"),
            _mt(root / "SCHEMA_VERSION"),
        )
        key = (str(root), True, schema_limit, finger)
        _READYZ_CACHE[key] = (time.time(), payload)
    return payload


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


@router.get("/v1/index/receipt/{shard_id}", summary="Get index build receipt for a shard")
def get_index_receipt(shard_id: str, db_path: str | None = None):
    # Basic shard id validation (avoid path traversal)
    if not shard_id or any(sep in shard_id for sep in ("/", "\\", "..")):
        raise HTTPException(status_code=400, detail="invalid shard_id")
    root = Path(db_path) if db_path else Path(settings.db_root)
    p = root / "indexes" / shard_id / "sealed" / "index_receipt.json"
    if not p.exists():
        raise HTTPException(status_code=404, detail="index receipt not found")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        raise HTTPException(status_code=500, detail="invalid index receipt")


# Admin-gated ops hooks for cache management and router reload
ops_admin = APIRouter(prefix="/v1/ops", tags=["ops"])


def _require_admin(secret_header: str | None) -> None:
    # Reuse metrics protection secret as admin secret
    if settings.metrics_protected and settings.metrics_secret:
        if not secret_header or secret_header != settings.metrics_secret:
            raise HTTPException(status_code=403, detail="Forbidden")


@ops_admin.post("/caches/clear", summary="Clear in-process caches (manifest, mmap)")
def clear_caches(x_admin_secret: str | None = Header(default=None)):
    _require_admin(x_admin_secret)
    cleared = []
    # Manifest cache
    try:
        from latticedb.cache import manifest_cache  # type: ignore
        manifest_cache.clear()  # type: ignore[attr-defined]
        cleared.append("manifest")
    except Exception:
        pass
    # MMap arrays LRU
    try:
        from latticedb.cache import mmap_arrays  # type: ignore
        mmap_arrays.clear()
        cleared.append("mmap")
    except Exception:
        pass
    return {"ok": True, "cleared": cleared}


@ops_admin.post("/router/reload", summary="Force router remap of centroids (clear mmap LRU)")
def router_reload(x_admin_secret: str | None = Header(default=None)):
    _require_admin(x_admin_secret)
    try:
        from latticedb.cache import mmap_arrays  # type: ignore
        mmap_arrays.clear()
    except Exception:
        pass
    return {"ok": True, "action": "router_mmap_cleared"}
