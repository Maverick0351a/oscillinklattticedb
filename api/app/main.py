"""SPDX-License-Identifier: BUSL-1.1"""
from __future__ import annotations

import asyncio
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .core.config import setup_logging, settings
from .core.tracing import setup_tracing
from .core.metrics import metrics_middleware, metrics_endpoint
from .core.middleware import install_http_middlewares
from .routers import ops as ops_router
from .routers import manifest as manifest_router
from .routers import latticedb as latticedb_router
from latticedb.embeddings import _load_registry


setup_logging()

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

setup_tracing(app)
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
app.include_router(manifest_router.router)
app.include_router(latticedb_router.router)


if settings.enable_test_endpoints:
    @app.get("/__test/slow", tags=["ops"], summary="Test-only slow endpoint")
    async def __test_slow(seconds: float = 0.1):
        await asyncio.sleep(max(0.0, float(seconds)))
        return {"slept": seconds}
