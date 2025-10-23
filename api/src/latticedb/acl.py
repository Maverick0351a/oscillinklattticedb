from __future__ import annotations

from pathlib import Path
from typing import List, Optional

def _as_items(x) -> list:
    try:
        if isinstance(x, (list, tuple, set)):
            return list(x)
        try:
            import numpy as np  # type: ignore
            if isinstance(x, np.ndarray):
                return x.tolist()
        except Exception:
            pass
        # Fallback: non-iterables or unsupported types
        return []
    except Exception:
        return []


def _find_lattice_dir(root: Path, lattice_id: str) -> Optional[Path]:
    try:
        for p in (root / "groups").glob(f"**/{lattice_id}"):
            if p.is_dir():
                return p
    except Exception:
        return None
    return None


def is_lattice_allowed(root: Path, lattice_id: str, *, tenant: Optional[str] = None, roles: Optional[List[str]] = None) -> bool:
    """Check ACL on a lattice by scanning its chunks.parquet briefly.

    Rules (best-effort, warn-mode semantics):
    - If no tenant/roles provided and ACL enforcement is off, allow.
    - Missing chunks.parquet or columns → allow (backward-compat).
    - If tenant provided, allow if any row contains it in acl_tenants.
    - If roles provided, allow if any row has intersection with acl_roles.
    - If both provided, require both to match.
    """
    if not tenant and not roles:
        # If no filters provided, treat as allow here; enforcement policy (deny-on-missing-claims)
        # is applied at the API layer before calling this helper.
        return True
    ldir = _find_lattice_dir(root, lattice_id)
    if not ldir:
        return True
    cparq = ldir / "chunks.parquet"
    if not cparq.exists():
        return True
    try:
        import pandas as pd  # type: ignore
        df = pd.read_parquet(cparq)
        cols = set(map(str, df.columns))
        # Public override: allow regardless of tenant/roles
        try:
            if "acl_public" in cols:
                view_pub = df.head(200)
                if bool(view_pub["acl_public"].astype(bool).any()):
                    return True
        except Exception:
            pass
        try:
            if "acl_tenants" in cols:
                view_pub = df.head(200)
                if bool(view_pub["acl_tenants"].apply(lambda x: any(str(i) == "public" for i in _as_items(x))).any()):
                    return True
        except Exception:
            pass
        if "acl_tenants" not in cols and "acl_roles" not in cols:
            return True
        # Sample a subset for speed
        view = df.head(200)
        ok_tenant = True
        ok_roles = True
        if tenant and "acl_tenants" in cols:
            try:
                ok_tenant = bool(
                    view["acl_tenants"].apply(lambda x: any(str(tenant) == str(i) for i in _as_items(x))).any()
                )
            except Exception:
                ok_tenant = True
        if roles and "acl_roles" in cols:
            rset = set(map(str, roles))
            try:
                ok_roles = bool(
                    view["acl_roles"].apply(lambda x: bool(rset.intersection(set(map(str, _as_items(x)))))).any()
                )
            except Exception:
                ok_roles = True
        if tenant and roles:
            return bool(ok_tenant and ok_roles)
        if tenant:
            return bool(ok_tenant)
        if roles:
            return bool(ok_roles)
        return True
    except Exception:
        return True
