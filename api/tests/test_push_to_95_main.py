from __future__ import annotations

from pathlib import Path
from fastapi.testclient import TestClient


def test_version_package_not_found(monkeypatch):
    import app.main as m

    def boom(_name: str):
        raise m.PackageNotFoundError

    monkeypatch.setattr(m, "pkg_version", boom)
    r = TestClient(m.app).get("/version")
    assert r.status_code == 200
    assert r.json()["version"].startswith("0.0.0+dev")


def test_manifest_created_from_invalid_date():
    import app.main as m

    # Invalid ISO should hit the _parse except path and simply filter nothing
    r = TestClient(m.app).get("/v1/latticedb/manifest", params={"created_from": "not-a-date"})
    assert r.status_code == 200
    assert "items" in r.json()


def test_route_config_json_invalid(monkeypatch, tmp_path: Path):
    import app.main as m

    # Prepare a db with invalid JSON in receipts/config.json to trigger try/except path
    db = tmp_path
    (db / "receipts").mkdir(parents=True)
    (db / "receipts" / "config.json").write_text("{not-json}")

    class DummyBE:
        def embed_queries(self, arr):
            return [[0.0]]

    def fake_load_model(model_id: str, device: str, batch_size: int, strict_hash: bool):  # noqa: ARG001
        return DummyBE()

    class FakeRouter:
        def __init__(self, root):
            self.root = root

        def route(self, _v, k: int = 8):  # noqa: ARG002
            return [("L-1", 0.5)]

    # Patch just the places api_route imports from
    import latticedb.embeddings as emb
    monkeypatch.setattr(emb, "load_model", fake_load_model)
    # Patch the Router symbol used by app.main (imported at module level)
    monkeypatch.setattr(m, "Router", FakeRouter)

    r = TestClient(m.app).post(
        "/v1/latticedb/route",
        json={"db_path": str(db), "q": "hello", "k_lattices": 1},
    )
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body.get("candidates"), list)
    assert body["candidates"] and set(body["candidates"][0].keys()) == {"lattice_id", "score"}


def test_compose_citations_path(monkeypatch, tmp_path: Path):
    import app.main as m

    # Minimal FS with receipts/db_receipt.json
    db = tmp_path
    (db / "receipts").mkdir(parents=True)
    (db / "receipts" / "db_receipt.json").write_text('{"db_root": "abc", "config_hash": "xyz"}')

    # Router returns our known lattice id
    lid = "L-CITATE"

    class FakeRouter:
        def __init__(self, root):
            self.root = root

        def load_centroids(self):
            return ([0.0], [lid])

    def fake_composite_settle(_cents, _sel_idx, **_):
        # Ensure gating passes: low residual, high deltaH
        return (1.0, 3, 1e-6, "ehash-1")

    # Provide lightweight embedding metadata so preset path is covered without heavy models
    import latticedb.embeddings as emb

    def fake_load_model(*a, **k):  # noqa: ARG001
        class _M:
            pass

        return _M()

    def fake_preset_meta(_m):  # noqa: ARG001
        return {"embed_model": "x", "embed_dim": 1}

    # Pandas read_parquet returns a one-row frame with a text column
    import pandas as pd

    def fake_read_parquet(_p):  # noqa: ARG001
        return pd.DataFrame([{"text": "hello world"}])

    monkeypatch.setattr(m, "Router", FakeRouter)
    import latticedb.composite as comp
    monkeypatch.setattr(comp, "composite_settle", fake_composite_settle)
    monkeypatch.setattr(emb, "load_model", fake_load_model)
    monkeypatch.setattr(emb, "preset_meta", fake_preset_meta)
    monkeypatch.setattr(pd, "read_parquet", fake_read_parquet)

    # Ensure CompositeReceipt.build returns an object exposing lattice_ids
    import latticedb.receipts as receipts

    class _FakeComp:
        def __init__(self, lattice_ids):
            self.lattice_ids = lattice_ids

        def model_dump(self):
            return {"lattice_ids": self.lattice_ids}

    monkeypatch.setattr(receipts.CompositeReceipt, "build", lambda **kwargs: _FakeComp([lid]))

    # Create a group dir that will be discovered by the glob("**/lid")
    gdir = db / "groups" / "G-000001" / lid
    gdir.mkdir(parents=True)
    # chunks.parquet path is not actually read due to monkeypatched read_parquet

    # Force the glob used in code to return our directory regardless of platform differences
    from pathlib import Path as _P

    _orig_glob = _P.glob

    def _fake_glob(self, pattern):  # noqa: ARG001
        if str(self).replace("\\", "/").endswith("/groups"):
            return [gdir]
        return _orig_glob(self, pattern)

    monkeypatch.setattr(_P, "glob", _fake_glob)

    r = TestClient(m.app).post(
        "/v1/latticedb/compose",
        json={
            "db_path": str(db),
            "q": "what?",
            "lattice_ids": [lid],
            "epsilon": 1e-3,
            "tau": 0.1,
        },
    )
    assert r.status_code == 200
    body = r.json()
    ws = body.get("context_pack", {}).get("working_set", [])
    assert isinstance(ws, list) and len(ws) >= 1 and "text" in ws[0]
