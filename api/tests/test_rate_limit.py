from __future__ import annotations

from fastapi.testclient import TestClient


def test_rate_limit_429(tmp_path):
    from app.main import app, settings, _RL_STATE

    # Enable rate limiting and set a very low limit
    settings.rate_limit_enabled = True
    settings.rate_limit_requests = 2
    settings.rate_limit_period_seconds = 60

    # Reset in-memory state so test is deterministic
    _RL_STATE.clear()

    client = TestClient(app)

    # Use a cheap endpoint
    r1 = client.get("/health")
    assert r1.status_code == 200
    r2 = client.get("/health")
    assert r2.status_code == 200
    r3 = client.get("/health")
    assert r3.status_code == 429

    # Disable again to avoid cross-test interference
    from app.main import settings as _settings
    _settings.rate_limit_enabled = False
