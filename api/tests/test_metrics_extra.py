from starlette.testclient import TestClient


def test_metrics_protected_requires_secret(monkeypatch):
    import app.main as m
    from app.core import config as cfg

    monkeypatch.setattr(cfg.settings, "metrics_protected", True, raising=False)
    monkeypatch.setattr(cfg.settings, "metrics_secret", "s3cr3t", raising=False)

    client = TestClient(m.app)
    r_no = client.get("/metrics")
    assert r_no.status_code == 401
    r_ok = client.get("/metrics", headers={"x-admin-secret": "s3cr3t"})
    assert r_ok.status_code == 200


def test_metrics_middleware_counts_5xx(monkeypatch):
    import app.main as m
    from fastapi import HTTPException
    # Dynamically add an endpoint that returns 500 to exercise REQ_ERRORS branch
    @m.app.get("/__test/error")
    def _boom():  # pragma: no cover - exercised via request below
        raise HTTPException(status_code=500, detail="boom")

    client = TestClient(m.app)
    r = client.get("/__test/error")
    assert r.status_code == 500
