from fastapi.testclient import TestClient

def test_readyz_summary_probe_minimal():
    # Use app instance to call /readyz in summary mode
    from app import main as m
    c = TestClient(m.app)
    r = c.get("/readyz", params={"summary": True})
    assert r.status_code == 200
    body = r.json()
    assert "ready" in body and "checks" in body
    # Minimal keys present in summary payload
    ck = body.get("checks", {})
    for k in [
        "router_centroids_exists",
        "router_meta_exists",
        "db_receipt_exists",
        "config_exists",
        "manifest_exists",
    ]:
        assert k in ck


def test_readyz_strict_ttl_cache_hit():
    # Ensure strict TTL caching path executes (second call hits early-return cache)
    from app import main as m
    old = m.settings.readyz_strict_ttl_seconds
    try:
        m.settings.readyz_strict_ttl_seconds = 60
        c = TestClient(m.app)
        r1 = c.get("/readyz", params={"strict": True})
        assert r1.status_code == 200
        b1 = r1.json()
        # Second call should return promptly via TTL cache
        r2 = c.get("/readyz", params={"strict": True})
        assert r2.status_code == 200
        b2 = r2.json()
        # Payload equivalence is expected within TTL window
        assert isinstance(b1, dict) and isinstance(b2, dict)
        assert set(b1.keys()) == set(b2.keys())
        assert b1.get("ready") == b2.get("ready")
    finally:
        m.settings.readyz_strict_ttl_seconds = old


def test_readyz_manifest_cache_toggle():
    # Exercise both manifest_cache True and False branches in /readyz strict path
    from app import main as m
    c = TestClient(m.app)
    old = m.settings.manifest_cache
    try:
        m.settings.manifest_cache = True
        r_true = c.get("/readyz", params={"strict": True})
        assert r_true.status_code == 200
        body_true = r_true.json()
        assert "checks" in body_true and isinstance(body_true["checks"], dict)
        # Toggle off to hit fallback path
        m.settings.manifest_cache = False
        r_false = c.get("/readyz", params={"strict": True})
        assert r_false.status_code == 200
        body_false = r_false.json()
        assert "checks" in body_false and isinstance(body_false["checks"], dict)
    finally:
        m.settings.manifest_cache = old
