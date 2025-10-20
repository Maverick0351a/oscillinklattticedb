from __future__ import annotations

from pathlib import Path
from fastapi.testclient import TestClient


def test_rate_limit_in_memory_429(monkeypatch):
    import app.main as m

    # Enable in-memory limiter and trust XFF to exercise that branch
    m.settings.rate_limit_enabled = True
    m.settings.rate_limit_requests = 0
    m.settings.rate_limit_period_seconds = 60
    m.settings.trust_x_forwarded_for = True
    # Ensure no redis url so we hit in-memory path
    m.settings.rate_limit_redis_url = None

    c = TestClient(m.app)
    r = c.get("/health", headers={"x-forwarded-for": "1.2.3.4"})
    assert r.status_code == 429


def test_ollama_generate_success_and_error(monkeypatch):
    from app.routers import latticedb as lr
    import json
    from urllib.error import URLError
    import urllib.request as ur

    # Success path: fake urlopen returning JSON
    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"response": "ok", "prompt_eval_count": 2, "eval_count": 3}).encode("utf-8")

    def fake_urlopen(req, timeout=60.0):  # noqa: ARG001
        return FakeResp()

    monkeypatch.setattr(ur, "urlopen", fake_urlopen)
    res = lr._ollama_generate("http://127.0.0.1:11434", "m", "p", temperature=0.0, top_p=1.0, max_tokens=8, seed=0)
    assert res.get("ok") is True and res.get("answer") == "ok"

    # Error path: raise URLError
    def fake_urlopen_err(req, timeout=60.0):  # noqa: ARG001
        raise URLError("down")

    monkeypatch.setattr(ur, "urlopen", fake_urlopen_err)
    res2 = lr._ollama_generate("http://127.0.0.1:11434", "m", "p", temperature=0.0, top_p=1.0, max_tokens=8, seed=0)
    assert res2.get("ok") is False and "ollama_error" in res2.get("error", "")


def test_manifest_date_filter_and_sort(monkeypatch, tmp_path: Path):
    import app.main as m
    from app.routers import manifest as man

    # Patch Manifest.list_lattices
    class _M:
        def __init__(self, root):
            self.root = root

        def list_lattices(self):
            return [
                {"group_id": "G-1", "lattice_id": "L-1", "deltaH_total": 0.2, "created_at": "2024-01-01T00:00:00Z"},
                {"group_id": "G-2", "lattice_id": "L-2", "deltaH_total": 0.9, "created_at": "2024-02-01T00:00:00Z"},
            ]

    # Patch the symbol used inside the router module
    monkeypatch.setattr(man, "Manifest", _M)

    c = TestClient(m.app)
    r = c.get(
        "/v1/latticedb/manifest",
        params={
            "db_path": str(tmp_path),
            "created_from": "2024-01-15T00:00:00Z",
            "created_to": "2024-03-01T00:00:00Z",
            "sort_by": "deltaH_total",
            "sort_order": "desc",
        },
    )
    assert r.status_code == 200
    items = r.json().get("items", [])
    # Only L-2 remains and appears first
    assert len(items) == 1 and items[0]["lattice_id"] == "L-2"


def test_size_limit_413(monkeypatch):
    import app.main as m

    # Set a very small max_request_bytes so our header triggers 413
    m.settings.max_request_bytes = 1
    # Avoid raising server exceptions so we can assert on the response
    c = TestClient(m.app, raise_server_exceptions=False)
    r = c.get("/health", headers={"content-length": "10"})
    assert r.status_code == 413


def test_api_ingest_updates_gauges_and_receipt(monkeypatch, tmp_path: Path):
    import app.main as m
    # Stub ingest_dir to produce minimal receipt-like objects
    class R:
        def __init__(self, dh, fr):
            self.deltaH_total = dh
            self.final_residual = fr
            self.state_sig = "sig"

    import latticedb.ingest as ing

    monkeypatch.setattr(ing, "ingest_dir", lambda *a, **k: [R(0.5, 0.01), R(0.6, 0.02)])

    c = TestClient(m.app)
    out_dir = tmp_path / "db"
    inp = tmp_path / "in"
    inp.mkdir(parents=True, exist_ok=True)
    r = c.post(
        "/v1/latticedb/ingest",
        json={
            "input_dir": str(inp),
            "out_dir": str(out_dir),
            "dim": 8,
            "k": 2,
            "lambda_G": 1.0,
            "lambda_C": 0.5,
            "lambda_Q": 2.0,
            "tol": 1e-5,
            "max_iter": 4,
            "embed_model": "bge-small-en-v1.5",
            "embed_device": "cpu",
            "embed_batch_size": 1,
            "embed_strict_hash": False,
        },
    )
    assert r.status_code == 200
    # Should write receipts/db_receipt.json
    assert (out_dir / "receipts" / "db_receipt.json").exists()


def test_ops_db_receipt_404(tmp_path: Path):
    import app.main as m

    c = TestClient(m.app)
    r = c.get("/v1/db/receipt", params={"db_path": str(tmp_path)})
    assert r.status_code == 404
