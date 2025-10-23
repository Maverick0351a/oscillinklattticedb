"""Soft schema validators for DB artifacts (warn-mode).
SPDX-License-Identifier: BUSL-1.1
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


def validate_chunks_parquet(root: Path, *, limit: int = 50) -> List[str]:
    """Check that groups/*/*/chunks.parquet have expected columns.

    Warn-only: returns list of warning strings; never raises.
    Enforces v1.0 schema presence as warnings; legacy two-column schema yields a
    specific legacy warning instead of listing all missing fields for each file.
    """
    warnings: List[str] = []
    # v1.0 canonical schema columns (see docs):
    v1_cols = {
        "lattice_id",
        "doc_id",
        "chunk_id",
        "source_type",
        "mimetype",
        "path",
        "title",
        "author",
        "created_at",
        "modified_at",
        "page_or_row",
        "section_title",
        "section_level",
        "text",
        "text_sha256",
        "ocr_avg_conf",
        "ocr_low_conf",
        "tags",
        "acl_tenants",
        "acl_roles",
        "model_name",
        "model_sha256",
        "dim",
        "file_sha256",
        "offset_start",
        "offset_end",
    }
    legacy_cols = {"text", "meta"}
    try:
        import pandas as pd  # local import
        count = 0
        for p in (root / "groups").rglob("chunks.parquet"):
            if count >= limit:
                warnings.append("chunks_parquet_check_limit_reached")
                break
            try:
                df = pd.read_parquet(p)
                cols = set(map(str, df.columns))
                # If legacy schema detected, emit one concise warning
                if cols.issuperset(legacy_cols) and not cols.issuperset(v1_cols):
                    warnings.append(f"chunks_schema_legacy:{p.as_posix()}")
                else:
                    missing = v1_cols - cols
                    if missing:
                        warnings.append(f"chunks_missing_cols:{p.as_posix()}:{','.join(sorted(missing))}")
            except Exception as e:  # noqa: BLE001
                warnings.append(f"chunks_unreadable:{p.as_posix()}:{type(e).__name__}")
            count += 1
    except Exception:
        # If pandas isn't available or other fatal issues, emit a coarse warning
        warnings.append("chunks_check_failed")
    return warnings


def validate_lattice_receipts(root: Path, *, limit: int = 100) -> List[str]:
    """Check that lattice receipts exist and include minimal fields.

    Warn-only: returns list of warning strings; never raises.
    """
    warnings: List[str] = []
    count = 0
    for p in (root / "groups").rglob("receipt.json"):
        if count >= limit:
            warnings.append("lattice_receipts_check_limit_reached")
            break
        try:
            rj = json.loads(p.read_text())
            if not rj.get("state_sig"):
                warnings.append(f"lattice_receipt_missing_state_sig:{p.as_posix()}")
            if not rj.get("version"):
                warnings.append(f"lattice_receipt_missing_version:{p.as_posix()}")
        except Exception as e:  # noqa: BLE001
            warnings.append(f"lattice_receipt_unreadable:{p.as_posix()}:{type(e).__name__}")
        count += 1
    return warnings


def soft_schema_validate(root: Path, *, schema_limit: int | None = None) -> Dict[str, Any]:
    """Run warn-mode schema checks and return a dict with warnings.

    Never raises; intended for readiness probes.
    """
    warns: List[str] = []
    # Clamp and apply sampling limits if provided
    if schema_limit is None:
        chunks_limit = 50
        receipts_limit = 100
    else:
        L = max(1, int(schema_limit))
        chunks_limit = L
        receipts_limit = min(L * 2, max(L, 1))
    warns += validate_chunks_parquet(root, limit=chunks_limit)
    # Binary artifacts checks (warn-mode)
    warns += validate_binary_artifacts(root, limit=chunks_limit)
    warns += validate_lattice_receipts(root, limit=receipts_limit)
    # Index receipts (warn-mode)
    warns += validate_index_receipts(root, limit=receipts_limit)
    # Manifest schema checks (warn-mode)
    try:
        import pandas as pd  # type: ignore
        manifest = root / "manifest.parquet"
        if not manifest.exists():
            warns.append("manifest_missing")
        else:
            try:
                dman = pd.read_parquet(manifest)
                req_cols = {"lattice_id", "group_id", "created_at", "source_file", "chunk_count", "file_bytes", "file_sha256"}
                cols = set(map(str, dman.columns))
                missing = req_cols - cols
                if missing:
                    warns.append("manifest_missing_cols:" + ",".join(sorted(missing)))
                if len(dman) <= 0:
                    warns.append("manifest_empty")
            except Exception as e:  # noqa: BLE001
                warns.append(f"manifest_unreadable:{type(e).__name__}")
    except Exception:
        warns.append("manifest_check_failed")
    return {"warnings": warns}


def validate_binary_artifacts(root: Path, *, limit: int = 50) -> List[str]:
    """Warn on missing or suboptimal binary artifacts under groups/*/*.

    - Prefer embeds.npy; warn if only embeds.f32 exists.
    - Warn if neither embeds.npy nor embeds.f32 exist.
    - Warn if edges binary missing.
    """
    warns: List[str] = []
    count = 0
    for g in (root / "groups").glob("G-*/L-*"):
        if count >= limit:
            warns.append("binary_artifacts_check_limit_reached")
            break
        try:
            has_npy = (g / "embeds.npy").exists()
            has_f32 = (g / "embeds.f32").exists()
            if not has_npy and has_f32:
                warns.append(f"embeds_npy_missing:{g.as_posix()}")
            if not has_npy and not has_f32:
                warns.append(f"embeds_missing:{g.as_posix()}")
            if not (g / "edges.bin").exists():
                warns.append(f"edges_missing:{g.as_posix()}")
            # Optional: require CSR tri-file when enabled via env
            try:
                import os as _os
                if _os.environ.get("LATTICEDB_VALIDATE_EDGES_TRIFILE"):
                    edir = g / "edges"
                    ok = (edir / "indptr.u64").exists() and (edir / "indices.u32").exists() and (edir / "weights.f32").exists()
                    if not ok:
                        warns.append(f"edges_trifile_missing:{g.as_posix()}")
            except Exception:
                pass
        except Exception:
            # best-effort warnings only
            pass
        count += 1
    return warns


def validate_index_receipts(root: Path, *, limit: int = 100) -> List[str]:
    """Warn if sealed index directories are missing index_receipt.json or it's unreadable.

    Looks under indexes/*/sealed.
    """
    warns: List[str] = []
    count = 0
    indexes_root = root / "indexes"
    if not indexes_root.exists():
        return warns
    for idxdir in indexes_root.glob("*/sealed"):
        if count >= limit:
            warns.append("index_receipts_check_limit_reached")
            break
        try:
            receipt = idxdir / "index_receipt.json"
            if not receipt.exists():
                warns.append(f"index_receipt_missing:{idxdir.as_posix()}")
            else:
                try:
                    data = json.loads(receipt.read_text())
                    for k in ("backend_id", "index_hash"):
                        if not data.get(k):
                            warns.append(f"index_receipt_missing_field:{receipt.as_posix()}:{k}")
                except Exception as e:  # noqa: BLE001
                    warns.append(f"index_receipt_unreadable:{receipt.as_posix()}:{type(e).__name__}")
        except Exception:
            pass
        count += 1
    return warns
