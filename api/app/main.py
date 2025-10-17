"""SPDX-License-Identifier: BUSL-1.1"""
import logging
import sys
import time
import os
from importlib.metadata import version as pkg_version, PackageNotFoundError
# Ensure local 'src' is on sys.path when running from source (dev without editable install)
try:
    _BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../api
    _SRC_DIR = os.path.join(_BASE_DIR, "src")
    if _SRC_DIR not in sys.path:
        sys.path.insert(0, _SRC_DIR)
except Exception:
    pass
from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pathlib import Path
import hashlib
import json
from typing import Any
import jwt
import asyncio

from latticedb.router import Router
from latticedb.ingest import ingest_dir
from latticedb.receipts import CompositeReceipt
from latticedb.watcher import single_scan as watcher_single_scan
from latticedb.verify import verify_composite
from pydantic_settings import BaseSettings, SettingsConfigDict
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from latticedb.utils import Manifest
from fastapi.responses import JSONResponse
from latticedb.embeddings import _load_registry


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LATTICEDB_", env_file=".env", env_file_encoding="utf-8")
    # Default DB root to repo_root/latticedb (works cross-platform); can be overridden via env LATTICEDB_DB_ROOT
    db_root: str = os.path.abspath(os.path.join(_BASE_DIR, "..", "latticedb"))
    log_level: str = "INFO"
    cors_origins: list[str] = ["http://127.0.0.1:5173", "http://localhost:5173"]
    api_key_required: bool = False
    api_key: str | None = None
    max_request_bytes: int = 2 * 1024 * 1024  # 2 MiB
    # Simple in-memory rate limit (per client IP per path)
    rate_limit_enabled: bool = False
    rate_limit_requests: int = 60
    rate_limit_period_seconds: int = 60
    # Optional Redis-backed rate limiter. If redis_url is set and rate_limit_enabled=true, use Redis.
    rate_limit_redis_url: str | None = None
    # Trust proxy headers for client IP selection
    trust_x_forwarded_for: bool = False
    # Request timeout (seconds). 0 disables.
    request_timeout_seconds: float = 0.0
    # Max concurrent requests. 0 disables.
    max_concurrency: int = 0
    # Security headers
    enable_hsts: bool = False
    # Enable test-only endpoints (e.g., slow endpoint for timeouts/concurrency tests)
    enable_test_endpoints: bool = False
    # OpenTelemetry tracing (optional)
    otel_enabled: bool = False
    otel_service_name: str = "latticedb-api"
    otel_exporter_otlp_endpoint: str | None = None
    otel_sample_ratio: float = 1.0
    # JWT auth (HS256 by default). If enabled, mutating endpoints require a valid Bearer token.
    jwt_enabled: bool = False
    jwt_secret: str | None = None
    jwt_algorithms: list[str] = ["HS256"]
    jwt_audience: str | None = None
    jwt_issuer: str | None = None
    # JWKS support (RS256 etc.). When set, prefer JWKS validation.
    jwt_jwks_url: str | None = None
    jwt_leeway: int = 0
    jwt_cache_ttl_seconds: int = 300
    # SPD parameters (global defaults)
    spd_dim: int = 32
    spd_k_neighbors: int = 4
    spd_lambda_G: float = 1.0
    spd_lambda_C: float = 0.5
    spd_lambda_Q: float = 4.0
    spd_tol: float = 1e-5
    spd_max_iter: int = 256
    # Embeddings
    embed_model: str = "bge-small-en-v1.5"
    embed_device: str = "cpu"
    embed_batch_size: int = 32
    embed_strict_hash: bool = False
    # Metrics protection (optional). When enabled, /metrics requires X-Admin-Secret header matching this value.
    metrics_protected: bool = bool(int(os.environ.get("METRICS_PROTECTED", "0")))
    metrics_secret: str | None = os.environ.get("LATTICEDB_METRICS_SECRET")
    # License status & gating
    license_mode: str = os.environ.get("LATTICEDB_LICENSE_MODE", "dev")  # dev|trial|prod
    license_id: str | None = os.environ.get("LATTICEDB_LICENSE_ID")
    license_tier: str | None = os.environ.get("LATTICEDB_LICENSE_TIER")
    license_expiry: str | None = os.environ.get("LATTICEDB_LICENSE_EXPIRY")  # ISO8601
    saas_allowed: bool = bool(int(os.environ.get("LATTICEDB_SAAS_ALLOWED", "0")))


settings = Settings()


def _setup_logging():
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        fmt='{"ts":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s","name":"%(name)s"}',
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


_setup_logging()

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

# --- OpenTelemetry (optional) ---
def _setup_tracing():
    if not settings.otel_enabled:
        return
    try:
        # Local imports to avoid hard dependency when disabled
        from opentelemetry import trace  # type: ignore
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource  # type: ignore
        from opentelemetry.sdk.trace import TracerProvider  # type: ignore
        from opentelemetry.sdk.trace.export import BatchSpanProcessor  # type: ignore
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter  # type: ignore
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor  # type: ignore
        from opentelemetry.sdk.trace.sampling import TraceIdRatioBased  # type: ignore

        resource = Resource.create({SERVICE_NAME: settings.otel_service_name})
        provider = TracerProvider(resource=resource, sampler=TraceIdRatioBased(max(0.0, min(1.0, float(settings.otel_sample_ratio)))))
        trace.set_tracer_provider(provider)

        endpoint = settings.otel_exporter_otlp_endpoint or "http://127.0.0.1:4318/v1/traces"
        exporter = OTLPSpanExporter(endpoint=endpoint)
        span_processor = BatchSpanProcessor(exporter)
        provider.add_span_processor(span_processor)

        # Instrument FastAPI app
        FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
    except Exception:
        # Do not fail the app if tracing setup fails
        pass

_setup_tracing()

# --- Basic protections ---
@app.middleware("http")
async def size_limit_middleware(request: Request, call_next):
    cl = request.headers.get("content-length")
    try:
        if cl is not None and int(cl) > settings.max_request_bytes:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="request too large")
    except ValueError:
        # Ignore malformed content-length and proceed
        pass
    return await call_next(request)

# --- Simple in-memory rate limit ---
_RL_STATE: dict[tuple[str, str], tuple[int, int]] = {}

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if not settings.rate_limit_enabled:
        return await call_next(request)

    # Identify client and key (optionally using X-Forwarded-For)
    client = "unknown"
    try:
        if settings.trust_x_forwarded_for:
            xff = request.headers.get("x-forwarded-for")
            if xff:
                client = xff.split(",")[0].strip() or client
        if client == "unknown":
            client = request.client.host if request.client else "unknown"
    except Exception:
        client = "unknown"
    path = request.url.path
    now = int(time.time())
    period = max(1, int(settings.rate_limit_period_seconds))
    window_start = now - (now % period)

    # Redis-backed limiter if configured
    if settings.rate_limit_redis_url:
        try:
            import redis  # type: ignore
            r = redis.StrictRedis.from_url(settings.rate_limit_redis_url)
            key = f"rl:{client}:{path}:{window_start}"
            pipe = r.pipeline()
            pipe.incr(key, 1)
            pipe.expire(key, period + 1)
            cnt, _ = pipe.execute()
            if int(cnt) > int(settings.rate_limit_requests):
                try:
                    REQ_RATELIMITED.labels(path=path).inc()
                except Exception:
                    pass
                return JSONResponse(status_code=status.HTTP_429_TOO_MANY_REQUESTS, content={"detail": "rate limit exceeded"})
        except Exception:
            # Fallback to in-memory on Redis error
            pass

    # In-memory limiter (default / fallback)
    key_mem = (client, path)
    old = _RL_STATE.get(key_mem)
    if old and old[0] == window_start:
        count = old[1]
    else:
        count = 0
    if count >= int(settings.rate_limit_requests):
        try:
            REQ_RATELIMITED.labels(path=path).inc()
        except Exception:
            pass
        return JSONResponse(status_code=status.HTTP_429_TOO_MANY_REQUESTS, content={"detail": "rate limit exceeded"})
    _RL_STATE[key_mem] = (window_start, count + 1)
    return await call_next(request)

# --- Security headers ---
@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "DENY")
    if settings.enable_hsts:
        # Only meaningful when served over HTTPS/edge TLS
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response

# --- Request ID ---
@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    rid = request.headers.get("x-request-id")
    if not rid:
        import uuid
        rid = uuid.uuid4().hex
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    return response

# --- Max concurrency ---
_SEM: asyncio.Semaphore | None = None
_SEM_MAX: int | None = None

@app.middleware("http")
async def concurrency_middleware(request: Request, call_next):
    global _SEM, _SEM_MAX
    max_c = int(settings.max_concurrency)
    if max_c <= 0:
        return await call_next(request)
    if _SEM is None or _SEM_MAX != max_c:
        _SEM = asyncio.Semaphore(max_c)
        _SEM_MAX = max_c
    try:
        await asyncio.wait_for(_SEM.acquire(), timeout=0)
    except asyncio.TimeoutError:
        try:
            REQ_OVERLOADS.labels(path=request.url.path).inc()
        except Exception:
            pass
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"detail": "server overloaded"})
    try:
        return await call_next(request)
    finally:
        try:
            _SEM.release()
        except Exception:
            pass

# --- Request timeout ---
@app.middleware("http")
async def timeout_middleware(request: Request, call_next):
    tmo = float(settings.request_timeout_seconds)
    if tmo <= 0:
        return await call_next(request)
    try:
        return await asyncio.wait_for(call_next(request), timeout=tmo)
    except asyncio.TimeoutError:
        try:
            REQ_TIMEOUTS.labels(path=request.url.path).inc()
        except Exception:
            pass
        return JSONResponse(status_code=504, content={"detail": "request timeout"})

# --- Metrics ---
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


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start = time.perf_counter()
    path = request.url.path
    method = request.method
    response = None
    status_code = None
    try:
        try:
            REQ_INPROGRESS.inc()
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
            REQ_INPROGRESS.dec()
        except Exception:
            pass


def auth_guard():
    """Unified auth guard: if JWT is enabled, require Bearer token; else, optional API key guard."""
    from fastapi import Header

    async def _check(
        authorization: str | None = Header(default=None, alias="Authorization"),
        x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    ):
        # Prefer JWT when enabled
        if settings.jwt_enabled:
            if not authorization or not authorization.startswith("Bearer "):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="missing bearer token",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            token = authorization.split(" ", 1)[1].strip()
            try:
                # JWKS path if configured
                if settings.jwt_jwks_url:
                    key = _get_jwks_signing_key(token)
                    jwt.decode(
                        token,
                        key=key,
                        algorithms=settings.jwt_algorithms,
                        audience=settings.jwt_audience,
                        issuer=settings.jwt_issuer,
                        leeway=int(settings.jwt_leeway),
                    )
                else:
                    # Shared-secret path (HS*)
                    if not settings.jwt_secret:
                        raise RuntimeError("jwt_secret not configured")
                    jwt.decode(
                        token,
                        key=str(settings.jwt_secret),
                        algorithms=settings.jwt_algorithms,
                        audience=settings.jwt_audience,
                        issuer=settings.jwt_issuer,
                        leeway=int(settings.jwt_leeway),
                    )
            except Exception:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="invalid bearer token",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            return True
        # Fallback to API key when required
        if settings.api_key_required:
            if settings.api_key and x_api_key == settings.api_key:
                return True
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid api key")
        # Open by default
        return True

    return Depends(_check)

# --- JWKS client cache ---
_JWKS_CLIENT_CACHE: dict[str, tuple[object, float]] = {}

def _get_jwks_signing_key(token: str):
    """Retrieve signing key for token via JWKS URL with simple TTL cache."""
    if not settings.jwt_jwks_url:
        raise RuntimeError("JWKS URL not configured")
    url = settings.jwt_jwks_url
    now = time.time()
    client_tuple = _JWKS_CLIENT_CACHE.get(url)
    client = None
    if client_tuple is not None:
        c, created = client_tuple
        if now - created < max(1, int(settings.jwt_cache_ttl_seconds)):
            client = c
    if client is None:
        # Create fresh client and cache it
        try:
            jwks_client = jwt.PyJWKClient(url)
        except Exception as e:
            # If cannot instantiate, propagate
            raise e
        _JWKS_CLIENT_CACHE[url] = (jwks_client, now)
        client = jwks_client
    # Resolve key for the specific token
    signing_key = client.get_signing_key_from_jwt(token)  # type: ignore[attr-defined]
    return signing_key.key

class IngestReq(BaseModel):
    input_dir: str
    out_dir: str = "latticedb"
    # Optional overrides
    dim: int | None = None
    k: int | None = None
    lambda_G: float | None = None
    lambda_C: float | None = None
    lambda_Q: float | None = None
    tol: float | None = None
    max_iter: int | None = None
    # Embedding options
    embed_model: str | None = None
    embed_device: str | None = None
    embed_batch_size: int | None = None
    embed_strict_hash: bool | None = None

@app.get("/health", tags=["ops"], summary="Health check")
def health():
    return {"ok": True}

@app.get("/v1/license/status", tags=["license"], summary="Report license mode and metadata")
def license_status():
    return {
        "mode": settings.license_mode,
        "id": settings.license_id,
        "tier": settings.license_tier,
        "expiry": settings.license_expiry,
        "saas_allowed": settings.saas_allowed,
        "notice": "Not for production use" if settings.license_mode != "prod" else "Production license active",
    }


@app.get("/readyz", tags=["ops"], summary="Readiness probe", description="Checks presence and integrity of DB artifacts and that config_hash in db receipt matches receipts/config.json.")
def readyz(db_path: str | None = None):
    """Readiness probe: checks presence and basic integrity of DB artifacts.

    Returns JSON with ready flag and individual check results.
    """
    root = Path(db_path) if db_path else Path(settings.db_root)
    checks: dict[str, Any] = {}

    router_centroids = root / "router" / "centroids.f32"
    router_meta = root / "router" / "meta.parquet"
    db_receipt = root / "receipts" / "db_receipt.json"
    cfg = root / "receipts" / "config.json"
    manifest = root / "manifest.parquet"

    checks["router_centroids_exists"] = router_centroids.exists() and router_centroids.stat().st_size > 0
    checks["router_meta_exists"] = router_meta.exists()
    checks["db_receipt_exists"] = db_receipt.exists()
    checks["config_exists"] = cfg.exists()
    checks["manifest_exists"] = manifest.exists()

    # Validate config hash matches db receipt if available
    try:
        if cfg.exists() and db_receipt.exists():
            cfg_hash = hashlib.sha256(cfg.read_bytes()).hexdigest()
            dr = json.loads(db_receipt.read_text())
            checks["config_hash_matches"] = dr.get("config_hash") == cfg_hash
        else:
            checks["config_hash_matches"] = False
    except Exception:
        checks["config_hash_matches"] = False

    # Attempt to read router meta as parquet
    dmeta = None
    meta_count: int | None = None
    try:
        if router_meta.exists():
            import pandas as pd  # local import to keep import time lighter
            dmeta = pd.read_parquet(router_meta)
            checks["router_meta_readable"] = True
            meta_count = len(dmeta)
        else:
            checks["router_meta_readable"] = False
    except Exception:
        checks["router_meta_readable"] = False

    # Consistency between centroids and meta (and manifest if present)
    try:
        centroid_count = None
        if router_centroids.exists() and cfg.exists():
            cfg_obj = json.loads(cfg.read_text())
            dim = int(cfg_obj.get("dim", 32))
            if dim > 0:
                size = router_centroids.stat().st_size
                bytes_per = dim * 4
                if bytes_per > 0 and size % bytes_per == 0:
                    centroid_count = size // bytes_per
                else:
                    centroid_count = None
        if meta_count is not None and centroid_count is not None:
            checks["router_counts_consistent"] = int(centroid_count) == int(meta_count)
        else:
            checks["router_counts_consistent"] = False
        # If manifest exists, ensure router ids are a subset
        if manifest.exists() and dmeta is not None:
            import pandas as pd
            dman = pd.read_parquet(manifest)
            man_ids = set(dman["lattice_id"].astype(str).tolist()) if "lattice_id" in dman.columns else set()
            meta_ids = set(dmeta["lattice_id"].astype(str).tolist()) if "lattice_id" in dmeta.columns else set()
            checks["router_ids_in_manifest"] = meta_ids.issubset(man_ids) and len(meta_ids) > 0
        else:
            checks["router_ids_in_manifest"] = False
    except Exception:
        checks["router_counts_consistent"] = False
        checks["router_ids_in_manifest"] = False

    ready = all(bool(v) for v in checks.values())
    return {"ready": ready, "checks": checks}


@app.get("/livez", tags=["ops"], summary="Liveness probe")
def livez():
    return {"live": True}


@app.get("/version", tags=["ops"], summary="Service version")
def version():
    try:
        ver = pkg_version("oscillink-latticedb")
    except PackageNotFoundError:
        ver = "0.0.0+dev"
    git_sha = os.environ.get("GIT_SHA", "unknown")
    return {"version": ver, "git_sha": git_sha}


@app.get("/health/security", tags=["ops"], summary="Security posture")
def health_security():
    # Default posture: deny egress unless explicitly allowed
    egress_denied = True if not os.environ.get("LATTICEDB_EGRESS_ALLOWED") else False
    models_local_verified = True  # default posture in scaffold
    return {"egress": "denied" if egress_denied else "allowed", "models": "local-verified" if models_local_verified else "remote"}


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

@app.get("/v1/db/receipt", tags=["ops"], summary="Get DB Merkle receipt")
def get_db_receipt(db_path: str | None = None):
    root = Path(db_path) if db_path else Path(settings.db_root)
    p = root/"receipts"/"db_receipt.json"
    if not p.exists():
        raise HTTPException(status_code=404, detail="db receipt not found")
    try:
        data = json.loads(p.read_text())
        return data
    except Exception:
        raise HTTPException(status_code=500, detail="invalid db receipt")

@app.post("/v1/latticedb/ingest", tags=["latticedb"], summary="Ingest documents into lattice store")
def api_ingest(req: IngestReq, _auth=auth_guard()):
    # Use configured SPD parameters with optional overrides
    dim = req.dim or settings.spd_dim
    k = req.k or settings.spd_k_neighbors
    lamG = req.lambda_G or settings.spd_lambda_G
    lamC = req.lambda_C or settings.spd_lambda_C
    lamQ = req.lambda_Q or settings.spd_lambda_Q
    tol = req.tol or settings.spd_tol
    max_iter = req.max_iter or settings.spd_max_iter
    # Embedding options with defaults
    em = req.embed_model or settings.embed_model
    edev = req.embed_device or settings.embed_device
    ebsz = int(req.embed_batch_size or settings.embed_batch_size)
    estrict = bool(req.embed_strict_hash if req.embed_strict_hash is not None else settings.embed_strict_hash)
    receipts = ingest_dir(
        Path(req.input_dir),
        Path(req.out_dir),
        group_by="doc.section",
        dim=dim,
        k=k,
        lambda_G=lamG,
        lambda_C=lamC,
        lambda_Q=lamQ,
        tol=tol,
        max_iter=max_iter,
        embed_model=em,
        embed_device=edev,
        embed_batch_size=ebsz,
        embed_strict_hash=estrict,
    )
    # Update SPD gauges from the last receipt if present
    if receipts:
        try:
            SPD_DELTAH_LAST.set(float(receipts[-1].deltaH_total))
            SPD_RESIDUAL_LAST.set(float(receipts[-1].final_residual))
        except Exception:
            pass
    from latticedb.merkle import merkle_root
    leaves = [r.state_sig for r in receipts]
    cfg_path = Path(req.out_dir)/"receipts"/"config.json"
    if cfg_path.exists():
        config_hash = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
    else:
        config_hash = hashlib.sha256(b"stub-config").hexdigest()
    root = merkle_root(leaves + [config_hash])
    (Path(req.out_dir)/"receipts").mkdir(parents=True, exist_ok=True)
    (Path(req.out_dir)/"receipts/db_receipt.json").write_text(json.dumps({"version":"1","db_root":root,"config_hash":config_hash}, indent=2))
    return {"count": len(receipts), "db_root": root}

class RouteReq(BaseModel):
    db_path: str | None = None
    q: str
    k_lattices: int = 8
    embed_model: str | None = None
    embed_device: str | None = None
    embed_batch_size: int | None = None
    embed_strict_hash: bool | None = None

@app.post("/v1/latticedb/route", tags=["latticedb"], summary="Route query to candidate lattices")
def api_route(req: RouteReq):
    # Use embedding backend based on DB config if available; allow overrides for ad-hoc testing
    from latticedb.embeddings import load_model
    # Default to service settings
    model_id = req.embed_model or settings.embed_model
    device = req.embed_device or settings.embed_device
    bsz = int(req.embed_batch_size or settings.embed_batch_size)
    strict = bool(req.embed_strict_hash if req.embed_strict_hash is not None else settings.embed_strict_hash)
    # If DB has config.json, prefer its embed_model to avoid mismatches
    try:
        root = Path(req.db_path) if req.db_path else Path(settings.db_root)
        cfgp = root/"receipts"/"config.json"
        if cfgp.exists():
            cfg = json.loads(cfgp.read_text())
            model_id = str(cfg.get("embed_model", model_id))
    except Exception:
        pass
    be = load_model(model_id, device=device, batch_size=bsz, strict_hash=strict)
    v = be.embed_queries([req.q])[0]
    r = Router(root)
    cand = r.route(v, k=req.k_lattices)
    return {"candidates": [{"lattice_id": lid, "score": s} for lid,s in cand]}

class ComposeReq(BaseModel):
    db_path: str | None = None
    q: str
    lattice_ids: list[str]
    epsilon: float = 1e-3
    tau: float = 0.30
    # Optional overrides for composite settle
    k: int | None = None
    lambda_G: float | None = None
    lambda_C: float | None = None
    lambda_Q: float | None = None
    tol: float | None = None
    max_iter: int | None = None

@app.post("/v1/latticedb/compose", tags=["latticedb"], summary="Compose selected lattices into a context pack")
def api_compose(req: ComposeReq, _auth=auth_guard()):
    from latticedb.router import Router
    from latticedb.composite import composite_settle
    from latticedb.embeddings import load_model, preset_meta
    root = Path(req.db_path) if req.db_path else Path(settings.db_root)
    cents, ids = Router(root).load_centroids()
    id_to_idx = {lid:i for i,lid in enumerate(ids)}
    sel_idx = [id_to_idx[i] for i in req.lattice_ids if i in id_to_idx]
    # Compute composite settle over selected centroids
    # Pull overrides or defaults
    k = req.k or settings.spd_k_neighbors
    lamG = req.lambda_G or settings.spd_lambda_G
    lamC = req.lambda_C or settings.spd_lambda_C
    lamQ = req.lambda_Q or settings.spd_lambda_Q
    tol = req.tol or settings.spd_tol
    max_iter = req.max_iter or settings.spd_max_iter
    dH, iters, resid, ehash = composite_settle(cents, sel_idx, k=k, lambda_G=lamG, lambda_C=lamC, lambda_Q=lamQ, tol=tol, max_iter=max_iter)

    # Include embedding provenance (query side) from DB config
    try:
        cfgp = root/"receipts"/"config.json"
        q_meta = {}
        if cfgp.exists():
            cfg = json.loads(cfgp.read_text())
            model_id = str(cfg.get("embed_model", settings.embed_model))
            be = load_model(model_id, device=settings.embed_device, batch_size=int(settings.embed_batch_size), strict_hash=bool(settings.embed_strict_hash))
            q_meta = preset_meta(be)
    except Exception:
        q_meta = {}

    comp = CompositeReceipt.build(
        db_root=json.loads((root/'receipts/db_receipt.json').read_text())["db_root"],
        lattice_ids=[ids[i] for i in sel_idx],
        edge_hash_composite=ehash,
        deltaH_total=dH,
        cg_iters=iters,
        final_residual=resid,
        epsilon=req.epsilon,
        tau=req.tau,
        filters={},
        model_sha256=(q_meta.get("weights_sha256") or "stub-model-sha256"),
        embed_model=q_meta.get("embed_model"),
        embed_dim=q_meta.get("embed_dim"),
        prompt_format=q_meta.get("prompt_format"),
        hf_rev=q_meta.get("hf_rev"),
        tokenizer_sha256=q_meta.get("tokenizer_sha256"),
        device=q_meta.get("device"),
        batch_size=q_meta.get("batch_size"),
        pooling=q_meta.get("pooling"),
        strict_hash=q_meta.get("strict_hash"),
    )
    # Optional simple gating: drop context if deltaH below tau or residual above epsilon
    if not (resid <= req.epsilon and dH >= req.tau):
        return {"context_pack": {"question": req.q, "working_set": [], "receipts": {"composite": comp.model_dump()} }}

    citations = []
    for lid in comp.lattice_ids:
        group_dir = next((p for p in (root/"groups").glob("**/"+lid) if p.is_dir()), None)
        if not group_dir:
            continue
        import pandas as pd
        df = pd.read_parquet(group_dir/"chunks.parquet")
        if len(df)>0:
            citations.append({"lattice": lid, "text": str(df.iloc[0]["text"])[:200], "score": 0.8})
    return {"context_pack": {"question": req.q, "working_set": citations, "receipts": {"composite": comp.model_dump()} } }

class VerifyReq(BaseModel):
    db_path: str | None = None
    composite: dict
    lattice_receipts: dict

@app.post("/v1/latticedb/verify", tags=["latticedb"], summary="Verify CompositeReceipt and lattice receipts")
def api_verify(req: VerifyReq):
    root = Path(req.db_path) if req.db_path else Path(settings.db_root)
    res = verify_composite(root/"receipts/db_receipt.json", req.composite, req.lattice_receipts)
    return res

# --- Test-only endpoints ---
if settings.enable_test_endpoints:
    @app.get("/__test/slow", tags=["ops"], summary="Test-only slow endpoint")
    async def __test_slow(seconds: float = 0.1):
        await asyncio.sleep(max(0.0, float(seconds)))
        return {"slept": seconds}


@app.get("/metrics", tags=["ops"], summary="Prometheus metrics")
def metrics(request: Request):
    # Optional protection: require X-Admin-Secret when enabled
    if settings.metrics_protected:
        secret = request.headers.get("x-admin-secret")
        if not (settings.metrics_secret and secret == settings.metrics_secret):
            raise HTTPException(status_code=401, detail="metrics protected")
    data = generate_latest()
    from fastapi.responses import Response
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


@app.get("/v1/latticedb/manifest", tags=["manifest"], summary="List lattices from the manifest")
def api_manifest(
    db_path: str | None = None,
    limit: int = 100,
    offset: int = 0,
    group_id: str | None = None,
    lattice_id: str | None = None,
    edge_hash: str | None = None,
    min_deltaH: float | None = None,
    max_deltaH: float | None = None,
    source_file: str | None = None,
    created_from: str | None = None,  # ISO8601
    created_to: str | None = None,    # ISO8601
    sort_by: str | None = None,  # one of: group_id, lattice_id, deltaH_total
    sort_order: str = "asc",  # asc|desc
):
    """List lattices from the manifest with basic filtering and sorting (Phase 2 prep)."""
    man = Manifest(Path(db_path) if db_path else Path(settings.db_root))
    rows = man.list_lattices()

    # Filtering
    if group_id:
        rows = [r for r in rows if r.get("group_id") == group_id]
    if lattice_id:
        rows = [r for r in rows if r.get("lattice_id") == lattice_id]
    if edge_hash:
        rows = [r for r in rows if r.get("edge_hash") == edge_hash]
    if source_file:
        rows = [r for r in rows if str(r.get("source_file","")) == source_file]
    if min_deltaH is not None:
        rows = [r for r in rows if float(r.get("deltaH_total", 0.0)) >= float(min_deltaH)]
    if max_deltaH is not None:
        rows = [r for r in rows if float(r.get("deltaH_total", 0.0)) <= float(max_deltaH)]
    # Time window filter
    if created_from or created_to:
        from datetime import datetime
        def _parse(ts: str) -> datetime | None:
            try:
                # accept 'Z' and offsets
                if ts.endswith('Z'):
                    ts = ts[:-1] + '+00:00'
                return datetime.fromisoformat(ts)
            except Exception:
                return None
        dt_from = _parse(created_from) if created_from else None
        dt_to = _parse(created_to) if created_to else None
        def _in_window(r):
            ts = str(r.get("created_at",""))
            d = _parse(ts)
            if d is None:
                return False
            ok = True
            if dt_from is not None:
                ok = ok and (d >= dt_from)
            if dt_to is not None:
                ok = ok and (d <= dt_to)
            return ok
        rows = [r for r in rows if _in_window(r)]

    # Sorting
    if sort_by in {"group_id", "lattice_id", "deltaH_total"}:
        rev = sort_order.lower() == "desc"
        if sort_by == "deltaH_total":
            rows = sorted(rows, key=lambda r: float(r.get("deltaH_total", 0.0)), reverse=rev)
        else:
            rows = sorted(rows, key=lambda r: str(r.get(sort_by, "")), reverse=rev)

    total = len(rows)
    limit_clamped = max(0, min(500, int(limit)))
    off = max(0, int(offset))
    slice_rows = rows[off:off+limit_clamped]
    return {"total": total, "items": slice_rows}


@app.get("/v1/latticedb/search", tags=["manifest"], summary="Search manifest by substring")
def api_search(db_path: str | None = None, q: str = "", limit: int = 100, offset: int = 0):
    """Simple substring search across manifest fields (group_id, lattice_id, source_file, edge_hash)."""
    man = Manifest(Path(db_path) if db_path else Path(settings.db_root))
    rows = man.list_lattices()
    qn = q.strip().lower()
    if qn:
        def _match(r: dict) -> bool:
            for k in ("group_id","lattice_id","source_file","edge_hash"):
                v = str(r.get(k, "")).lower()
                if qn in v:
                    return True
            return False
        rows = [r for r in rows if _match(r)]
    total = len(rows)
    limit_clamped = max(0, min(500, int(limit)))
    off = max(0, int(offset))
    return {"total": total, "items": rows[off:off+limit_clamped]}


class ScanReq(BaseModel):
    input_dir: str
    out_dir: str | None = None
    embed_model: str | None = None
    embed_device: str | None = None
    embed_batch_size: int | None = None
    embed_strict_hash: bool | None = None


@app.post("/v1/db/scan", tags=["latticedb"], summary="Run a single watcher scan")
def api_db_scan(req: ScanReq, _auth=auth_guard()):
    root = Path(req.out_dir) if req.out_dir else Path(settings.db_root)
    res = watcher_single_scan(
        Path(req.input_dir),
        root,
        embed_model=req.embed_model or settings.embed_model,
        embed_device=req.embed_device or settings.embed_device,
        embed_batch_size=int(req.embed_batch_size or settings.embed_batch_size),
        embed_strict_hash=bool(req.embed_strict_hash if req.embed_strict_hash is not None else settings.embed_strict_hash),
    )
    return res