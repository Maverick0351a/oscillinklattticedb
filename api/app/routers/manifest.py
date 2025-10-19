"""Manifest listing, search, and metadata endpoints.
SPDX-License-Identifier: BUSL-1.1
"""
from __future__ import annotations

from pathlib import Path
from fastapi import APIRouter, HTTPException

from ..core.config import settings
from ..schemas import LatticeMetadataReq
from ..auth.jwt import auth_guard
from ..services.metadata_service import load_names, save_names
from latticedb.utils import Manifest


router = APIRouter(tags=["manifest"])


@router.get("/v1/latticedb/manifest", summary="List lattices from the manifest")
def api_manifest(
    db_path: str | None = None,
    limit: int = 100,
    offset: int = 0,
    group_id: str | None = None,
    lattice_id: str | None = None,
    edge_hash: str | None = None,
    min_deltaH: float | None = None,
    max_deltaH: float | None = None,
    source_file: str | None = None,
    created_from: str | None = None,  # ISO8601
    created_to: str | None = None,    # ISO8601
    display_name: str | None = None,
    sort_by: str | None = None,  # one of: group_id, lattice_id, deltaH_total, display_name
    sort_order: str = "asc",  # asc|desc
):
    root = Path(db_path) if db_path else Path(settings.db_root)
    man = Manifest(root)
    rows = man.list_lattices()

    try:
        names = load_names(root)
        for r in rows:
            lid = str(r.get("lattice_id", ""))
            if lid in names:
                r["display_name"] = names[lid]
    except Exception:
        pass

    if group_id:
        rows = [r for r in rows if r.get("group_id") == group_id]
    if lattice_id:
        rows = [r for r in rows if r.get("lattice_id") == lattice_id]
    if edge_hash:
        rows = [r for r in rows if r.get("edge_hash") == edge_hash]
    if source_file:
        rows = [r for r in rows if str(r.get("source_file","")) == source_file]
    if display_name:
        rows = [r for r in rows if str(r.get("display_name","")) == display_name]
    if min_deltaH is not None:
        rows = [r for r in rows if float(r.get("deltaH_total", 0.0)) >= float(min_deltaH)]
    if max_deltaH is not None:
        rows = [r for r in rows if float(r.get("deltaH_total", 0.0)) <= float(max_deltaH)]

    if created_from or created_to:
        from datetime import datetime
        def _parse(ts: str) -> datetime | None:
            try:
                if ts.endswith('Z'):
                    ts = ts[:-1] + '+00:00'
                return datetime.fromisoformat(ts)
            except Exception:
                return None
        dt_from = _parse(created_from) if created_from else None
        dt_to = _parse(created_to) if created_to else None
        def _in_window(r):
            ts = str(r.get("created_at",""))
            d = _parse(ts)
            if d is None:
                return False
            ok = True
            if dt_from is not None:
                ok = ok and (d >= dt_from)
            if dt_to is not None:
                ok = ok and (d <= dt_to)
            return ok
        rows = [r for r in rows if _in_window(r)]

    if sort_by in {"group_id", "lattice_id", "deltaH_total", "display_name"}:
        rev = sort_order.lower() == "desc"
        if sort_by == "deltaH_total":
            rows = sorted(rows, key=lambda r: float(r.get("deltaH_total", 0.0)), reverse=rev)
        else:
            rows = sorted(rows, key=lambda r: str(r.get(sort_by, "")), reverse=rev)

    total = len(rows)
    limit_clamped = max(0, min(500, int(limit)))
    off = max(0, int(offset))
    slice_rows = rows[off:off+limit_clamped]
    return {"total": total, "items": slice_rows}


@router.get("/v1/latticedb/search", summary="Search manifest by substring")
def api_search(db_path: str | None = None, q: str = "", limit: int = 100, offset: int = 0):
    root = Path(db_path) if db_path else Path(settings.db_root)
    man = Manifest(root)
    rows = man.list_lattices()
    try:
        names = load_names(root)
        for r in rows:
            lid = str(r.get("lattice_id", ""))
            if lid in names:
                r["display_name"] = names[lid]
    except Exception:
        pass
    qn = q.strip().lower()
    if qn:
        def _match(r: dict) -> bool:
            for k in ("group_id","lattice_id","source_file","edge_hash"):
                v = str(r.get(k, "")).lower()
                if qn in v:
                    return True
            dv = str(r.get("display_name", "")).lower()
            if qn in dv:
                return True
            return False
        rows = [r for r in rows if _match(r)]
    total = len(rows)
    limit_clamped = max(0, min(500, int(limit)))
    off = max(0, int(offset))
    return {"total": total, "items": rows[off:off+limit_clamped]}


@router.put("/v1/latticedb/lattice/{lattice_id}/metadata", tags=["latticedb"], summary="Set lattice metadata (display_name)")
def set_lattice_metadata(lattice_id: str, req: LatticeMetadataReq, _auth=auth_guard()):
    root = Path(req.db_path) if req.db_path else Path(settings.db_root)
    rows = Manifest(root).list_lattices()
    if not any(str(r.get("lattice_id")) == lattice_id for r in rows):
        raise HTTPException(status_code=404, detail="lattice_id not found")
    name = req.display_name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="display_name cannot be empty")
    if len(name) > 256:
        raise HTTPException(status_code=400, detail="display_name too long (max 256)")
    names = load_names(root)
    names[lattice_id] = name
    save_names(root, names)
    return {"ok": True, "lattice_id": lattice_id, "display_name": name}
