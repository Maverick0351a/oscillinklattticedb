from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_version_and_metrics():
    client = TestClient(app)

    v = client.get("/version")
    assert v.status_code == 200
    data = v.json()
    assert "version" in data and "git_sha" in data

    m = client.get("/metrics")
    assert m.status_code == 200
    # Should contain our metric names
    body = m.text
    assert "http_requests_total" in body and "http_request_duration_seconds" in body
