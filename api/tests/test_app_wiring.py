"""Lightweight smoke tests to ensure the FastAPI app is assembled correctly.

These tests avoid heavy endpoints (ingest/route/compose) and instead validate
that core routers are present and key lightweight endpoints respond.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings


client = TestClient(app)


def test_health_and_liveness():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json().get("ok") is True

    r = client.get("/livez")
    assert r.status_code == 200
    assert r.json().get("live") is True


def test_version_endpoint():
    r = client.get("/version")
    assert r.status_code == 200
    body = r.json()
    assert "version" in body


def test_openapi_contains_expected_routes():
    r = client.get("/openapi.json")
    assert r.status_code == 200
    spec = r.json()

    # Tags from routers
    tags = [t["name"] for t in spec.get("tags", [])]
    for expected in ("ops", "manifest", "latticedb"):
        assert expected in tags

    # A couple of representative paths that should be registered via routers
    paths = spec.get("paths", {}).keys()
    assert "/readyz" in paths
    assert "/v1/latticedb/manifest" in paths
    assert "/v1/latticedb/compose" in paths


def test_metrics_endpoint_reachable_or_protected():
    r = client.get("/metrics")
    # If metrics are protected, 401 is acceptable; otherwise expect 200
    if settings.metrics_protected:
        assert r.status_code in (200, 401)
    else:
        assert r.status_code == 200
        ctype = r.headers.get("content-type", "")
        assert ctype.startswith("text/plain")


def test_models_endpoint_exists():
    r = client.get("/v1/latticedb/models")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data.get("items"), list)
