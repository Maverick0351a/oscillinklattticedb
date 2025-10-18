import sys
import pytest
from pathlib import Path

# Ensure the project root (containing the `app` package) is on sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Global test hygiene: snapshot and restore app settings and global state per test


@pytest.fixture(autouse=True)
def restore_app_settings():
    from app import main as m
    snap = {
        # Core toggles
        "max_request_bytes": m.settings.max_request_bytes,
        "enable_hsts": m.settings.enable_hsts,
        "metrics_protected": m.settings.metrics_protected,
        "metrics_secret": m.settings.metrics_secret,
        "jwt_enabled": m.settings.jwt_enabled,
        "jwt_secret": m.settings.jwt_secret,
        "jwt_algorithms": list(m.settings.jwt_algorithms),
        "jwt_audience": m.settings.jwt_audience,
        "jwt_issuer": m.settings.jwt_issuer,
        "jwt_jwks_url": m.settings.jwt_jwks_url,
        "jwt_leeway": m.settings.jwt_leeway,
        "jwt_cache_ttl_seconds": m.settings.jwt_cache_ttl_seconds,
        "api_key_required": m.settings.api_key_required,
        "api_key": m.settings.api_key,
        "request_timeout_seconds": m.settings.request_timeout_seconds,
        "max_concurrency": m.settings.max_concurrency,
        "trust_x_forwarded_for": m.settings.trust_x_forwarded_for,
        # Rate limit
        "rate_limit_enabled": m.settings.rate_limit_enabled,
        "rate_limit_requests": m.settings.rate_limit_requests,
        "rate_limit_period_seconds": m.settings.rate_limit_period_seconds,
        "rate_limit_redis_url": m.settings.rate_limit_redis_url,
        # Test endpoints
        "enable_test_endpoints": m.settings.enable_test_endpoints,
    }
    try:
        yield
    finally:
        for k, v in snap.items():
            setattr(m.settings, k, v)
        # Clear limiter state and JWKS cache and reset semaphores to avoid leakage
        try:
            m._RL_STATE.clear()
        except Exception:
            pass
        try:
            m._JWKS_CLIENT_CACHE.clear()
        except Exception:
            pass
        try:
            m._SEM = None
            m._SEM_MAX = None
        except Exception:
            pass
