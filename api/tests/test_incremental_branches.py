from __future__ import annotations

from fastapi.testclient import TestClient
from pathlib import Path


def test_middleware_invalid_content_length_header():
    import app.main as m

    c = TestClient(m.app)
    # Invalid Content-Length should be ignored (no 413)
    r = c.get("/health", headers={"content-length": "NaN"})
    assert r.status_code == 200


def test_chat_backend_not_supported(monkeypatch):
    import app.main as m
    from app.routers import latticedb as lr

    # Enable LLM but select unsupported backend to trigger 400 path
    m.settings.llm_enabled = True
    m.settings.llm_backend = "bogus"
    # Stub out route/compose to avoid filesystem/model access
    monkeypatch.setattr(lr, "api_route", lambda req: {"candidates": []})
    monkeypatch.setattr(
        lr,
        "api_compose",
        lambda req, _auth=None: {"context_pack": {"question": "Q?", "working_set": [], "receipts": {}}},
    )
    c = TestClient(m.app)
    r = c.post("/v1/latticedb/chat", json={"db_path": str(Path.cwd()), "q": "Q?", "k_lattices": 1, "select": 0})
    assert r.status_code == 400
    assert "not supported" in r.json().get("detail", "")


def test_chat_ollama_error_502(monkeypatch):
    import app.main as m
    from app.routers import latticedb as lr

    m.settings.llm_enabled = True
    m.settings.llm_backend = "ollama"

    # Minimal stubs for route/compose
    monkeypatch.setattr(lr, "api_route", lambda req: {"candidates": []})
    monkeypatch.setattr(lr, "api_compose", lambda req, _auth=None: {"context_pack": {"question": "Q?", "working_set": [], "receipts": {}}})

    # Simulate backend error
    monkeypatch.setattr(lr, "_ollama_generate", lambda *a, **k: {"ok": False, "error": "boom"})

    c = TestClient(m.app)
    r = c.post("/v1/latticedb/chat", json={"db_path": str(Path.cwd()), "q": "Q?", "k_lattices": 1, "select": 0})
    assert r.status_code == 502


def test_compose_threshold_short_circuit(monkeypatch, tmp_path: Path):
    import app.main as m
    from app.routers import latticedb as lr
    from app.schemas import ComposeReq

    # Fake Router to avoid filesystem
    class _R:
        def __init__(self, root):
            self.root = root

        def load_centroids(self):
            import numpy as np

            C = np.eye(2, dtype=np.float32)
            ids = ["L-1", "L-2"]
            return C, ids

    # Monkeypatch Router resolution through app.main
    monkeypatch.setattr(m, "Router", _R, raising=False)

    # Write minimal db_receipt.json so compose can read db_root
    (tmp_path / "receipts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "receipts" / "db_receipt.json").write_text('{"db_root": "abc", "config_hash": "x"}')

    # Force composite_settle to return values that fail thresholds
    import latticedb.composite as comp
    monkeypatch.setattr(comp, "composite_settle", lambda *a, **k: (0.1, 1, 0.9, "eh"))

    req = ComposeReq(db_path=str(tmp_path), q="Q?", lattice_ids=["L-1"], k=1, epsilon=0.05, tau=0.95)
    res = lr.api_compose(req)  # type: ignore[arg-type]
    pack = res.get("context_pack", {})
    assert isinstance(pack, dict)
    assert pack.get("working_set") == []


def test_route_model_override(monkeypatch, tmp_path: Path):
    import app.main as m

    # Write config.json to override embed_model
    (tmp_path / "receipts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "receipts" / "config.json").write_text("{\n  \"embed_model\": \"bge-small-en-v1.5\"\n}")

    # Stub load_model to avoid heavy deps
    class _BE:
        def __init__(self):
            self.dim = 32

        def embed_queries(self, arr):  # noqa: ARG002
            import numpy as np

            return np.zeros((1, 32), dtype=np.float32)

    import latticedb.embeddings as emb

    monkeypatch.setattr(emb, "load_model", lambda *a, **k: _BE())

    # Stub Router.route
    class _R:
        def __init__(self, root):
            self.root = root

        def route(self, v, k=8):  # noqa: ARG002
            return [("L-1", 0.5)]

    monkeypatch.setattr(m, "Router", _R, raising=False)

    c = TestClient(m.app)
    r = c.post("/v1/latticedb/route", json={"db_path": str(tmp_path), "q": "Q?", "k_lattices": 1})
    assert r.status_code == 200
    body = r.json()
    assert body.get("candidates")


def test_compose_citations_path(monkeypatch, tmp_path: Path):
    import app.main as m
    from app.schemas import ComposeReq

    # Router mock
    class _R:
        def __init__(self, root):
            self.root = root

        def load_centroids(self):
            import numpy as np

            C = np.eye(2, dtype=np.float32)
            ids = ["L-1", "L-2"]
            return C, ids

    monkeypatch.setattr(m, "Router", _R, raising=False)

    # receipts
    (tmp_path / "receipts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "receipts" / "db_receipt.json").write_text('{"db_root": "abc", "config_hash": "x"}')

    # Ensure group dir exists so glob finds it
    (tmp_path / "groups" / "G-1" / "L-1").mkdir(parents=True, exist_ok=True)

    # Patch composite_settle to pass thresholds
    import latticedb.composite as comp

    monkeypatch.setattr(comp, "composite_settle", lambda *a, **k: (1.0, 5, 0.01, "eh"))

    # Patch pandas.read_parquet to return one row
    import pandas as pd

    def _fake_read_parquet(*a, **k):  # noqa: ARG001
        return pd.DataFrame({"text": ["snippet"], "lattice_id": ["L-1"]})

    import pandas as pd_mod

    monkeypatch.setattr(pd_mod, "read_parquet", _fake_read_parquet)

    # Also stub embeddings load_model/preset_meta path to avoid heavy deps and cover meta branch
    import latticedb.embeddings as emb

    class _BE:
        dim = 32
        device = "cpu"
        batch_size = 1
        strict_hash = False

    monkeypatch.setattr(emb, "load_model", lambda *a, **k: _BE())
    monkeypatch.setattr(emb, "preset_meta", lambda be: {"weights_sha256": "sha", "embed_model": "x", "embed_dim": 32})

    req = ComposeReq(db_path=str(tmp_path), q="Q?", lattice_ids=["L-1"], k=1, epsilon=0.05, tau=0.95)
    # Import locally to avoid unused import lint at module level
    from app.routers import latticedb as lr
    res = lr.api_compose(req)  # type: ignore[arg-type]
    pack = res.get("context_pack", {})
    assert pack.get("working_set")


def test_metadata_load_invalid_json(tmp_path: Path):
    from app.services import metadata_service as ms

    p = ms.names_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("not-json")
    # Should safely return empty dict on parse error
    assert ms.load_names(tmp_path) == {}


def test_ops_db_receipt_invalid_json(tmp_path: Path):
    import app.main as m

    # Write invalid JSON receipt and expect 500
    (tmp_path / "receipts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "receipts" / "db_receipt.json").write_text("not-json")
    c = TestClient(m.app)
    r = c.get("/v1/db/receipt", params={"db_path": str(tmp_path)})
    assert r.status_code == 500
