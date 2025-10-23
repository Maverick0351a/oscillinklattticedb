import json

import pytest


@pytest.fixture(autouse=True)
def _acl_env(monkeypatch):
    # Ensure ACL enforcement is on for these tests
    from app.core import config as cfg
    monkeypatch.setattr(cfg.settings, "acl_enforce", True, raising=False)
    yield


def _write_chunks(dirpath, tenants=None, roles=None):
    import pandas as pd
    df = pd.DataFrame(
        {
            "text": ["hello"],
            "acl_tenants": [tenants if tenants is not None else []],
            "acl_roles": [roles if roles is not None else []],
        }
    )
    (dirpath).mkdir(parents=True, exist_ok=True)
    df.to_parquet(dirpath / "chunks.parquet")


def test_route_acl_filters_candidates(tmp_path, monkeypatch):
    # DB root and minimal config to satisfy code paths
    root = tmp_path / "db"
    (root / "receipts").mkdir(parents=True)
    (root / "receipts" / "config.json").write_text(json.dumps({"embed_model": "stub", "embed_dim": 2}))

    # Create two lattices, only L-2 allows tenant 'acme'
    _write_chunks(root / "groups" / "G-1" / "L-1", tenants=["other"], roles=["reader"])  # excluded
    _write_chunks(root / "groups" / "G-2" / "L-2", tenants=["acme"], roles=["reader"])   # allowed

    import app.routers.latticedb as lr
    # No retrieval backend
    monkeypatch.setattr(lr.settings, "retrieval_backend", "", raising=False)

    # Stub embeddings
    class _StubBE:
        def embed_queries(self, arr):
            return [[0.0, 0.0]]

    monkeypatch.setattr("latticedb.embeddings.load_model", lambda *a, **k: _StubBE())

    # Stub Router to return both candidates
    class _StubRouter:
        def __init__(self, root):
            pass

        def route(self, v, k: int):
            return [("L-1", 0.9), ("L-2", 0.8)]

    import app.main as m
    monkeypatch.setattr(m, "Router", _StubRouter, raising=True)

    from app.schemas import RouteReq
    res = lr.api_route(RouteReq(db_path=str(root), q="q", k_lattices=2, tenant="acme"))
    lids = [c["lattice_id"] for c in res.get("candidates", [])]
    assert "L-1" not in lids and "L-2" in lids


def test_compose_acl_abstain(tmp_path, monkeypatch):
    import app.routers.latticedb as lr

    root = tmp_path / "db"
    (root / "groups" / "G-1" / "L-1").mkdir(parents=True)

    # Router centroids mapping includes L-1 so id_to_idx can resolve
    class _StubRouter:
        def __init__(self, root):
            pass

        def load_centroids(self):
            return [[0.0, 0.0]], ["L-1"]

    monkeypatch.setattr(lr, "_RouterLocal", _StubRouter, raising=False)

    # Compose settle returns good thresholds, but ACL should abstain earlier when empty
    monkeypatch.setattr("latticedb.composite.composite_settle", lambda *a, **k: (1.0, 5, 0.01, "ehash"))

    # DB receipt for provenance
    (root / "receipts").mkdir(parents=True)
    (root / "receipts" / "db_receipt.json").write_text(json.dumps({"db_root": "ROOT"}))

    # Lattice denies tenant 'acme'
    _write_chunks(root / "groups" / "G-1" / "L-1", tenants=["other"], roles=["reader"])  # excluded

    from app.schemas import ComposeReq
    resp = lr.api_compose(ComposeReq(db_path=str(root), q="q", lattice_ids=["L-1"], tenant="acme"))
    assert resp.get("abstain") is True and resp.get("reason") == "acl_no_candidates"
