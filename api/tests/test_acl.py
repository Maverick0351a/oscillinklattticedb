from __future__ import annotations

from pathlib import Path

from latticedb.acl import is_lattice_allowed


def _make_lattice(tmp: Path, gid: str, lid: str, tenants=None, roles=None):
    gdir = tmp / "groups" / gid / lid
    gdir.mkdir(parents=True, exist_ok=True)
    import pandas as pd  # type: ignore
    df = pd.DataFrame(
        {
            "text": ["hello world"],
            "acl_tenants": [tenants if tenants is not None else []],
            "acl_roles": [roles if roles is not None else []],
        }
    )
    df.to_parquet(gdir / "chunks.parquet")
    return gdir


def test_acl_no_filters_allows(tmp_path):
    _make_lattice(tmp_path, "G-1", "L-1", tenants=["t1"], roles=["admin"])
    assert is_lattice_allowed(tmp_path, "L-1") is True


def test_acl_with_tenant_role_filters(tmp_path):
    _make_lattice(tmp_path, "G-1", "L-1", tenants=["t1"], roles=["admin", "reader"])
    # Tenant match
    assert is_lattice_allowed(tmp_path, "L-1", tenant="t1") is True
    # Tenant mismatch
    assert is_lattice_allowed(tmp_path, "L-1", tenant="t2") is False
    # Role match
    assert is_lattice_allowed(tmp_path, "L-1", roles=["reader"]) is True
    # Role mismatch
    assert is_lattice_allowed(tmp_path, "L-1", roles=["writer"]) is False
    # Both must match
    assert is_lattice_allowed(tmp_path, "L-1", tenant="t1", roles=["admin"]) is True
    assert is_lattice_allowed(tmp_path, "L-1", tenant="t1", roles=["writer"]) is False
