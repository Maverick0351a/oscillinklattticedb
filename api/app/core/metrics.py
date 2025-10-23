"""Prometheus metrics and middleware.
SPDX-License-Identifier: BUSL-1.1
"""
from __future__ import annotations

import time
from fastapi import Request, HTTPException
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from fastapi.responses import Response
from .config import settings


# HTTP metrics
REQ_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    labelnames=("method", "path", "status"),
)
REQ_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    labelnames=("method", "path"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
REQ_INPROGRESS = Gauge(
    "http_inprogress_requests",
    "Number of HTTP requests in progress",
)
REQ_ERRORS = Counter(
    "http_requests_errors_total",
    "Total HTTP requests with 5xx responses",
    labelnames=("method", "path", "status"),
)
REQ_TIMEOUTS = Counter(
    "http_request_timeouts_total",
    "Requests that timed out (returned 504)",
    labelnames=("path",),
)
REQ_OVERLOADS = Counter(
    "http_requests_overload_total",
    "Requests rejected due to max concurrency (503)",
    labelnames=("path",),
)
REQ_RATELIMITED = Counter(
    "http_rate_limited_total",
    "Requests rejected due to rate limiting (429)",
    labelnames=("path",),
)

# SPD metrics (last observed during ingest)
SPD_DELTAH_LAST = Gauge(
    "spd_deltaH_last",
    "Last observed total energy reduction during ingest (micro-lattice)",
)
SPD_RESIDUAL_LAST = Gauge(
    "spd_residual_last",
    "Last observed final residual during ingest (micro-lattice)",
)

# ACL metrics
ACL_FILTERED_CANDIDATES = Counter(
    "latticedb_acl_filtered_candidates_total",
    "Total candidates filtered by ACL",
    labelnames=("endpoint",),
)
ACL_ABSTAIN = Counter(
    "latticedb_acl_abstain_total",
    "Total abstains due to ACL",
    labelnames=("reason",),
)

# LatticeDB operation latencies
route_latency = Histogram(
    "latticedb_route_seconds",
    "Route latency (s)",
    buckets=(0.01, 0.02, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)
compose_latency = Histogram(
    "latticedb_compose_seconds",
    "Compose latency (s)",
    buckets=(0.01, 0.02, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)


async def metrics_middleware(request: Request, call_next):
    start = time.perf_counter()
    path = request.url.path
    method = request.method
    response = None
    status_code = None
    try:
        try:
            # Allow tests to swap the gauge via app.main
            from .. import main as _m  # type: ignore
            g = getattr(_m, "REQ_INPROGRESS", REQ_INPROGRESS)
            g.inc()
        except Exception:
            pass
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        dur = time.perf_counter() - start
        REQ_LATENCY.labels(method=method, path=path).observe(dur)
        sc = status_code if status_code is not None else (response.status_code if response is not None else 500)
        REQ_COUNT.labels(method=method, path=path, status=str(sc)).inc()
        try:
            if int(sc) >= 500:
                REQ_ERRORS.labels(method=method, path=path, status=str(sc)).inc()
        except Exception:
            pass
        try:
            from .. import main as _m  # type: ignore
            g = getattr(_m, "REQ_INPROGRESS", REQ_INPROGRESS)
            g.dec()
        except Exception:
            pass


def metrics_endpoint(request: Request):
    # Optional protection: require X-Admin-Secret when enabled
    if settings.metrics_protected:
        secret = request.headers.get("x-admin-secret")
        if not (settings.metrics_secret and secret == settings.metrics_secret):
            raise HTTPException(status_code=401, detail="metrics protected")
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)
