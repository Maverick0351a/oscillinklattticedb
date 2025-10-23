from __future__ import annotations

from fastapi.testclient import TestClient

from app import main as m


def test_caches_clear_and_router_reload_admin_protected(monkeypatch):
    client = TestClient(m.app)
    # Snapshot settings
    snap = {
        "metrics_protected": m.settings.metrics_protected,
        "metrics_secret": m.settings.metrics_secret,
    }
    try:
        m.settings.metrics_protected = True
        m.settings.metrics_secret = "s"

        # Missing header -> 403
        r1 = client.post("/v1/ops/caches/clear")
        assert r1.status_code == 403
        # Correct header -> 200
        r2 = client.post("/v1/ops/caches/clear", headers={"X-Admin-Secret": "s"})
        assert r2.status_code == 200
        assert r2.json().get("ok") is True

        r3 = client.post("/v1/ops/router/reload")
        assert r3.status_code == 403
        r4 = client.post("/v1/ops/router/reload", headers={"X-Admin-Secret": "s"})
        assert r4.status_code == 200
        assert r4.json().get("ok") is True
    finally:
        m.settings.metrics_protected = snap["metrics_protected"]
        m.settings.metrics_secret = snap["metrics_secret"]
