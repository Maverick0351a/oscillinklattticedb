"""Core configuration and logging for LatticeDB FastAPI app.
SPDX-License-Identifier: BUSL-1.1
"""
from __future__ import annotations

import logging
import os
import sys
from pydantic_settings import BaseSettings, SettingsConfigDict


# Ensure local 'src' is on sys.path when running from source (dev without editable install)
try:
    _BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../api
    _SRC_DIR = os.path.join(_BASE_DIR, "src")
    if _SRC_DIR not in sys.path:
        sys.path.insert(0, _SRC_DIR)
except Exception:
    pass


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LATTICEDB_", env_file=".env", env_file_encoding="utf-8")
    # Default DB root to repo_root/latticedb (works cross-platform); can be overridden via env LATTICEDB_DB_ROOT
    db_root: str = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "latticedb"))
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
    # Optional LLM integration (local-only recommended, disabled by default)
    llm_enabled: bool = bool(int(os.environ.get("LATTICEDB_LLM_ENABLED", "0")))
    llm_backend: str = os.environ.get("LATTICEDB_LLM_BACKEND", "ollama")  # ollama|llama.cpp|custom
    llm_endpoint: str = os.environ.get("LATTICEDB_LLM_ENDPOINT", "http://127.0.0.1:11434")
    llm_model: str = os.environ.get("LATTICEDB_LLM_MODEL", "mistral")
    llm_temperature: float = float(os.environ.get("LATTICEDB_LLM_TEMPERATURE", "0.0"))
    llm_top_p: float = float(os.environ.get("LATTICEDB_LLM_TOP_P", "1.0"))
    llm_max_tokens: int = int(os.environ.get("LATTICEDB_LLM_MAX_TOKENS", "512"))
    llm_seed: int = int(os.environ.get("LATTICEDB_LLM_SEED", "0"))
    # Retrieval adapters (optional)
    retrieval_backend: str = os.environ.get("LATTICEDB_RETRIEVAL_BACKEND", "")
    deterministic_mode: bool = bool(int(os.environ.get("OSC_DETERMINISTIC", os.environ.get("LATTICEDB_DETERMINISTIC", "0"))))


settings = Settings()


def setup_logging() -> None:
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
