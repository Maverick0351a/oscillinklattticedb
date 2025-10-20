from __future__ import annotations

from fastapi.testclient import TestClient
from pathlib import Path


def test_chat_endpoint_success(monkeypatch, tmp_path: Path):
    # Import module under test
    import app.main as m
    from app.routers import latticedb as lr

    # Enable LLM and set backend
    m.settings.llm_enabled = True
    m.settings.llm_backend = "ollama"
    m.settings.llm_endpoint = "http://127.0.0.1:11434"
    m.settings.llm_model = "stub-model"

    # Stub route and compose to avoid filesystem/model deps
    monkeypatch.setattr(lr, "api_route", lambda req: {"candidates": [{"lattice_id": "L-1", "score": 0.9}]})
    monkeypatch.setattr(
        lr,
        "api_compose",
        lambda req, _auth=None: {
            "context_pack": {
                "question": req.q,  # type: ignore[attr-defined]
                "working_set": [{"lattice": "L-1", "text": "hello"}],
                "receipts": {},
            }
        },
    )

    # Stub LLM call
    monkeypatch.setattr(
        lr,
        "_ollama_generate",
        lambda endpoint, model, prompt, **kwargs: {  # noqa: ARG005
            "ok": True,
            "answer": "hi",
            "tokens": {"prompt": 1, "completion": 1},
        },
    )

    c = TestClient(m.app)
    r = c.post(
        "/v1/latticedb/chat",
        json={"db_path": str(tmp_path), "q": "Q?", "k_lattices": 1, "select": 1},
    )
    assert r.status_code == 200
    body = r.json()
    assert body.get("chat", {}).get("answer") == "hi"


def test_db_scan_endpoint(monkeypatch, tmp_path: Path):
    import app.main as m
    from app.routers import latticedb as lr

    inp = tmp_path / "in"
    out = tmp_path / "out"
    inp.mkdir(parents=True)
    out.mkdir(parents=True)

    # Stub watcher to avoid heavy work
    monkeypatch.setattr(lr, "watcher_single_scan", lambda *a, **k: {"ok": True})

    c = TestClient(m.app)
    r = c.post(
        "/v1/db/scan",
        json={"input_dir": str(inp), "out_dir": str(out)},
    )
    assert r.status_code == 200
    assert r.json().get("ok") is True


def test_metadata_service_roundtrip(tmp_path: Path):
    # Directly test names load/save helpers
    from app.services import metadata_service as ms

    root = tmp_path
    p = ms.names_path(root)
    # Directory is created on save
    assert not p.parent.exists()
    ms.save_names(root, {"L-1": "Contract"})
    assert p.parent.exists()
    got = ms.load_names(root)
    assert got == {"L-1": "Contract"}
