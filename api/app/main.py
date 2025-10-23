"""SPDX-License-Identifier: BUSL-1.1

Back-compat shim: this module re-exports several symbols that older tests
expect to exist directly on ``app.main`` even though the implementation now
lives in submodules. These exports are no-ops for runtime but make tests able
to monkeypatch specific paths.
"""
from __future__ import annotations

import asyncio
import os
from fastapi import FastAPI, Request
from pathlib import Path
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import setup_logging, settings
from app.core.tracing import setup_tracing as _setup_tracing_impl
from app.core.metrics import metrics_middleware, metrics_endpoint, REQ_INPROGRESS as REQ_INPROGRESS
from app.core.middleware import (
    install_http_middlewares,
    RL_STATE as _RL_STATE_impl,
    rate_limit_middleware as rate_limit_middleware,
    SEM as _SEM_impl,
    SEM_MAX as _SEM_MAX_impl,
)
from app.routers import ops as ops_router
from app.routers import manifest as manifest_router
from app.routers import latticedb as latticedb_router
from app.auth.jwt import (
    _JWKS_CLIENT_CACHE as _JWKS_CLIENT_CACHE,  # compat: tests import from app.main
    _get_jwks_signing_key as _get_jwks_signing_key,
)
import jwt as jwt  # re-export for tests expecting m.jwt
import time as time  # re-export for tests patching m.time
from importlib.metadata import version as pkg_version, PackageNotFoundError  # re-export for tests patching version handling
from latticedb.router import Router as Router  # re-export for tests patching m.Router
from latticedb.embeddings import _load_registry

setup_logging()

# keep references to satisfy linters about re-exports
_pkg_version_ref = pkg_version
_pkg_exc_ref = PackageNotFoundError

tags_metadata = [
    {"name": "ops", "description": "Operational health, readiness, version, and metrics."},
    {"name": "latticedb", "description": "Core ingest, route, compose, verify flows."},
    {"name": "manifest", "description": "Manifest listing, filtering, and search."},
    {"name": "license", "description": "License status and mode."},
]

app = FastAPI(title="Oscillink LatticeDB (Scaffold)", openapi_tags=tags_metadata)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Wrapper so tests can import _setup_tracing from app.main
def _setup_tracing() -> None:  # pragma: no cover - covered indirectly in tests
    try:
        _setup_tracing_impl(app)
    except Exception:
        pass

_setup_tracing()
install_http_middlewares(app)


app.middleware("http")(metrics_middleware)


@app.get("/v1/latticedb/models", tags=["latticedb"], summary="List available embedding presets")
def list_models():
    reg = _load_registry()
    items = []
    for k, p in reg.items():
        items.append({
            "id": k,
            "hf": p.hf,
            "dim": p.dim,
            "license": p.license,
            "prompt_format": p.prompt_format,
        })
    return {"items": items}


@app.get("/metrics", tags=["ops"], summary="Prometheus metrics")
def metrics(request: Request):
    return metrics_endpoint(request)


app.include_router(ops_router.router)
app.include_router(ops_router.ops_admin)
app.include_router(manifest_router.router)
app.include_router(latticedb_router.router)


if settings.enable_test_endpoints or str(os.environ.get("LATTICEDB_ENABLE_TEST_ENDPOINTS", "")).lower() in ("1", "true", "yes"):
    @app.get("/__test/slow", tags=["ops"], summary="Test-only slow endpoint")
    async def __test_slow(seconds: float = 0.1):
        await asyncio.sleep(max(0.0, float(seconds)))
        return {"slept": seconds}


@app.on_event("startup")
async def _preload_router() -> None:  # pragma: no cover - warmup optimization
    """Preload router centroids to reduce first-query latency.

    Best-effort; swallow errors to avoid blocking startup.
    """
    try:
        Router(Path(settings.db_root)).load_centroids()
    except Exception:
        pass

# Re-export middleware globals so tests can clear/patch:
_RL_STATE = _RL_STATE_impl
_SEM = _SEM_impl
_SEM_MAX = _SEM_MAX_impl
