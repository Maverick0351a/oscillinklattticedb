import json
import pytest


def test_route_403_when_missing_claims_and_deny_on_missing(monkeypatch, tmp_path):
    from app.core import config as cfg
    import app.routers.latticedb as lr

    # Enforce ACL and deny when missing
    monkeypatch.setattr(cfg.settings, "acl_enforce", True, raising=False)
    monkeypatch.setattr(cfg.settings, "acl_deny_on_missing_claims", True, raising=False)

    root = tmp_path / "db"
    (root / "receipts").mkdir(parents=True)
    (root / "receipts" / "config.json").write_text(json.dumps({"embed_model": "stub", "embed_dim": 2}))

    # Stub embeddings
    class _StubBE:
        def embed_queries(self, arr):
            return [[0.0, 0.0]]

    monkeypatch.setattr("latticedb.embeddings.load_model", lambda *a, **k: _StubBE())

    # Stub Router
    class _StubRouter:
        def __init__(self, root):
            pass

        def route(self, v, k: int):
            return [("L-1", 1.0)]

    import app.main as m
    monkeypatch.setattr(m, "Router", _StubRouter, raising=True)

    from app.schemas import RouteReq

    with pytest.raises(Exception):
        lr.api_route(RouteReq(db_path=str(root), q="q", k_lattices=1))


def test_acl_public_allows_even_if_tenant_mismatch(tmp_path):
    from latticedb.acl import is_lattice_allowed
    import pandas as pd

    root = tmp_path / "db"
    d = root / "groups" / "G-1" / "L-1"
    d.mkdir(parents=True)

    # Mark as public via acl_public
    df = pd.DataFrame({"text": ["t"], "acl_public": [True]})
    df.to_parquet(d / "chunks.parquet")

    # Tenant mismatch still allowed due to public
    assert is_lattice_allowed(root, "L-1", tenant="acme") is True

    # Also allow public via 'public' entry in acl_tenants
    df2 = pd.DataFrame({"text": ["t"], "acl_tenants": [["public"]]})
    d2 = root / "groups" / "G-1" / "L-2"
    d2.mkdir(parents=True)
    df2.to_parquet(d2 / "chunks.parquet")

    assert is_lattice_allowed(root, "L-2", tenant="other") is True
