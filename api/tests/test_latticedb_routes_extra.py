import json
from types import SimpleNamespace
from typing import List

import pytest


@pytest.fixture(autouse=True)
def _isolate_settings(monkeypatch):
    # Ensure tests don't inherit unexpected env; toggle determinism-friendly values
    from app.core import config as cfg

    # Keep a snapshot for selective restore if needed
    snapshot = {
        "retrieval_backend": cfg.settings.retrieval_backend,
        "deterministic_mode": cfg.settings.deterministic_mode,
        "llm_enabled": cfg.settings.llm_enabled,
        "llm_backend": cfg.settings.llm_backend,
        "llm_endpoint": cfg.settings.llm_endpoint,
        "llm_model": cfg.settings.llm_model,
        "embed_model": cfg.settings.embed_model,
    }
    # Defaults for tests
    monkeypatch.setattr(cfg.settings, "deterministic_mode", True, raising=False)
    try:
        yield
    finally:
        # Best-effort restore of mutated settings
        for k, v in snapshot.items():
            try:
                monkeypatch.setattr(cfg.settings, k, v, raising=False)
            except Exception:
                pass


def test_api_route_uses_retrieval_backend_when_configured(tmp_path, monkeypatch):
    # Arrange: minimal DB layout and stubbed embeddings
    root = tmp_path / "db"
    (root / "receipts").mkdir(parents=True)
    (root / "receipts" / "config.json").write_text(json.dumps({"embed_model": "stub", "embed_dim": 4}))
    # Stub embeddings loader
    class _StubBE:
        def embed_queries(self, arr: List[str]):
            return [[0.1, 0.2, 0.3, 0.4]]

    monkeypatch.setenv("LATTICEDB_DETERMINISTIC", "1")
    import app.routers.latticedb as lr
    monkeypatch.setattr(lr.settings, "retrieval_backend", "stub:backend", raising=False)

    # Stub backend instance with expected API
    calls = SimpleNamespace(build=[], query=[])

    class _StubBackend:
        def build(self, db_root: str, index_dir: str, dim: int | None = None):
            calls.build.append((db_root, index_dir, dim))
            return {"ok": True, "dim": dim}

        def query(self, v: List[float], k: int = 1):
            calls.query.append((v, k))
            return [
                {"id": "L-1", "score": 0.9},
                {"id": "L-2", "score": 0.5},
            ]

    # Patch resolve_backend and determinism setter
    def _resolve_backend(spec: str):
        assert spec == "stub:backend"
        return ("stub:backend", _StubBackend(), {"spec": spec})

    monkeypatch.setattr("latticedb.retrieval.base.resolve_backend", _resolve_backend)
    monkeypatch.setattr("latticedb.retrieval.base.set_determinism_env", lambda **_: None)
    monkeypatch.setattr("latticedb.embeddings.load_model", lambda *a, **k: _StubBE())

    from app.schemas import RouteReq

    # Act
    res = lr.api_route(RouteReq(db_path=str(root), q="hello", k_lattices=2))

    # Assert
    assert isinstance(res, dict) and "candidates" in res
    assert [c["lattice_id"] for c in res["candidates"]] == ["L-1", "L-2"]
    # ensure build/query were exercised
    assert calls.build and calls.query


def test_api_route_fallback_to_router_on_adapter_failure(tmp_path, monkeypatch):
    # Arrange
    root = tmp_path / "db"
    (root / "receipts").mkdir(parents=True)
    (root / "receipts" / "config.json").write_text(json.dumps({"embed_model": "stub", "embed_dim": 2}))
    import app.routers.latticedb as lr
    # Force retrieval path then raise inside adapter to trigger fallback
    monkeypatch.setattr(lr.settings, "retrieval_backend", "boom:adapter", raising=False)
    monkeypatch.setattr("latticedb.retrieval.base.resolve_backend", lambda *_: (_ for _ in ()).throw(RuntimeError("boom")))
    # Stub embeddings
    class _StubBE:
        def embed_queries(self, arr):
            return [[0.0, 0.0]]

    monkeypatch.setattr("latticedb.embeddings.load_model", lambda *a, **k: _StubBE())

    # Stub Router used inside function: patch app.main.Router which api_route prefers
    class _StubRouter:
        def __init__(self, root):
            self.root = root

        def route(self, v, k: int):
            return [("FALLBACK", 1.0)]
    import app.main as m
    monkeypatch.setattr(m, "Router", _StubRouter, raising=True)

    from app.schemas import RouteReq
    res = lr.api_route(RouteReq(db_path=str(root), q="x", k_lattices=1))
    assert res["candidates"][0]["lattice_id"] == "FALLBACK"


def test_api_compose_returns_empty_working_set_when_thresholds_not_met(tmp_path, monkeypatch):
    import app.routers.latticedb as lr
    # Minimal groups layout for id mapping
    root = tmp_path / "db"
    (root / "groups" / "G-000001" / "L-1").mkdir(parents=True)
    # Patch Router.load_centroids to provide a controlled set
    class _StubRouter:
        def __init__(self, root):
            pass

        def load_centroids(self):
            # two centroids with ids
            return [[0.0, 0.0], [1.0, 1.0]], ["L-1", "L-2"]

    monkeypatch.setattr(lr, "_RouterLocal", _StubRouter, raising=False)
    # Patch composite_settle with poor coherence
    monkeypatch.setattr("latticedb.composite.composite_settle", lambda *a, **k: (0.01, 10, 1.23, "ehash"))
    # Provide a receipts/db_receipt.json for provenance in CompositeReceipt.build
    (root / "receipts").mkdir(parents=True)
    (root / "receipts" / "db_receipt.json").write_text(json.dumps({"db_root": "ROOT"}))

    from app.schemas import ComposeReq
    # Set high thresholds so condition fails
    resp = lr.api_compose(ComposeReq(db_path=str(root), q="q", lattice_ids=["L-1"], epsilon=0.1, tau=0.5))
    pack = resp.get("context_pack", {})
    assert pack.get("working_set") == []
    # Ensure receipts are present
    assert "receipts" in pack and "composite" in pack["receipts"]


def test_build_prompt_formats_and_hashes():
    from app.routers.latticedb import _build_prompt

    prompt, ph = _build_prompt("What is Oscillink?", [{"text": "context", "lattice": "L-1"}])
    assert "Question: What is Oscillink?" in prompt
    assert len(ph) == 64


def test_ollama_generate_handles_network_error(monkeypatch):
    from app.routers.latticedb import _ollama_generate
    import urllib.error as uerr

    def boom(*a, **k):
        raise uerr.URLError("down")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    res = _ollama_generate("http://127.0.0.1:11434", "m", "p", temperature=0, top_p=1, max_tokens=1, seed=0)
    assert res["ok"] is False and "ollama_error" in res.get("error", "")


def test_api_chat_guard_when_llm_disabled(monkeypatch):
    from app.routers.latticedb import api_chat
    from app.schemas import ChatReq
    from app.core import config as cfg
    # Ensure disabled
    monkeypatch.setattr(cfg.settings, "llm_enabled", False, raising=False)
    with pytest.raises(Exception):
        api_chat(ChatReq(q="q"))


def test_api_chat_success_with_mocked_dependencies(tmp_path, monkeypatch):
    import app.routers.latticedb as lr
    from app.schemas import ChatReq
    from app.core import config as cfg

    # Enable LLM with ollama backend but mock network and subcalls
    monkeypatch.setattr(cfg.settings, "llm_enabled", True, raising=False)
    monkeypatch.setattr(cfg.settings, "llm_backend", "ollama", raising=False)
    monkeypatch.setattr(cfg.settings, "llm_endpoint", "http://127.0.0.1:11434", raising=False)
    monkeypatch.setattr(cfg.settings, "llm_model", "stub", raising=False)

    # Mock routing and compose to avoid heavy deps
    monkeypatch.setattr(lr, "api_route", lambda req: {"candidates": [{"lattice_id": "L-1", "score": 1.0}]})
    monkeypatch.setattr(
        lr,
        "api_compose",
        lambda req: {
            "context_pack": {
                "question": req.q,
                "working_set": [{"lattice": "L-1", "text": "hello"}],
                "receipts": {"composite": {"edge_hash_composite": "eh"}},
            }
        },
    )

    # Mock Ollama call to a fast local response
    monkeypatch.setattr(
        lr,
        "_ollama_generate",
        lambda endpoint, model, prompt, **kwargs: {"ok": True, "response": "A", "prompt_eval_count": 1, "eval_count": 2, "tokens": {"prompt": 1, "completion": 2}},
    )

    res = lr.api_chat(ChatReq(q="What?", select=1))
    assert "chat" in res and res["chat"]["answer"] is not None


def test_api_chat_unsupported_backend(monkeypatch):
    from app.routers.latticedb import api_chat
    from app.core import config as cfg
    from app.schemas import ChatReq
    monkeypatch.setattr(cfg.settings, "llm_enabled", True, raising=False)
    monkeypatch.setattr(cfg.settings, "llm_backend", "unknown", raising=False)
    with pytest.raises(Exception):
        api_chat(ChatReq(q="x"))


def test_api_db_scan_smoke(tmp_path, monkeypatch):
    from app.routers.latticedb import api_db_scan
    from app.schemas import ScanReq
    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir(parents=True)
    # Provide minimal stubs to bypass heavy dependencies
    monkeypatch.setattr("latticedb.watcher.single_scan", lambda *a, **k: {"ok": True})
    res = api_db_scan(ScanReq(input_dir=str(inp), out_dir=str(out)))
    assert isinstance(res, dict)


def test_api_route_handles_bad_config_json(tmp_path, monkeypatch):
    # Arrange malformed config to exercise exception path
    root = tmp_path / "db"
    (root / "receipts").mkdir(parents=True)
    (root / "receipts" / "config.json").write_text("{not json}")
    import app.routers.latticedb as lr
    # Force fallback path (no retrieval backend)
    monkeypatch.setattr(lr.settings, "retrieval_backend", "", raising=False)
    # Stub embeddings and Router
    class _StubBE:
        def embed_queries(self, arr):
            return [[0.0]]

    class _StubRouter:
        def __init__(self, root):
            pass

        def route(self, v, k: int):
            return [("X", 1.0)]

    monkeypatch.setattr("latticedb.embeddings.load_model", lambda *a, **k: _StubBE())
    import app.main as m
    monkeypatch.setattr(m, "Router", _StubRouter, raising=True)
    from app.schemas import RouteReq
    res = lr.api_route(RouteReq(db_path=str(root), q="q", k_lattices=1))
    assert res["candidates"][0]["lattice_id"] == "X"
