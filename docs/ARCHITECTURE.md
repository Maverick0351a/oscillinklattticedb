# Architecture

User → UI (React) → FastAPI
                  ├─ /v1/latticedb/ingest   (build micro-lattices with SPD, write receipts, update manifest)
                  ├─ /v1/latticedb/route    (route queries via centroid cosine similarity)
                  ├─ /v1/latticedb/compose  (SPD settle over selected centroids, optional gating)
                  ├─ /v1/latticedb/verify   (Merkle verification of receipts/config)
                  └─ /health, /readyz, /metrics

Store layout (append-only):
```
latticedb/
  manifest.parquet             # groups, lattice ids, meta (edge_hash, deltaH_total, source_file, etc.)
  groups/
    G-000001/
      L-000001/
        chunks.parquet
        embeds.f32
        edges.bin
        ustar.f32
        receipt.json
  router/
    centroids.f32
    meta.parquet
  receipts/
    config.json                # normalized build parameters
    db_receipt.json            # Merkle root over lattice state_sigs + config
```

SPD formulation:
- Mutual-kNN graph over embeddings (cosine), Laplacian L.
- System M = λG I + λC L + λQ B (pinning to centroid/query), solved with CG + Jacobi preconditioner.
- Energy H(U) tracked; receipts store ΔH_total, cg_iters, residual, and edge hashes.

Determinism:
- Deterministic embeddings (stub), mutual-kNN with stable sorts, normalized vectors, canonical JSON, sha256 over receipts & config.

## Backend modules (service layout)

The FastAPI backend is modular to keep concerns isolated and testable:

- api/app/core
  - config.py — service settings (pydantic-settings) and JSON-ish logging setup
  - tracing.py — optional OpenTelemetry setup when enabled via settings
  - metrics.py — Prometheus metrics, HTTP metrics middleware, /metrics endpoint helper
  - middleware.py — HTTP protections installed in a defined order (see below)
- api/app/auth
  - jwt.py — unified JWT/JWKS guard; also supports API-key only mode
- api/app/services
  - metadata_service.py — helpers for metadata/names.json (display_name mapping)
- api/app/routers
  - ops.py — health, livez, readyz, version, license, db receipt
  - manifest.py — manifest listing/filter/sort, search, and lattice metadata update
  - latticedb.py — ingest, route, compose, verify, chat, scan
- api/app/schemas.py — request models shared by routers
- api/app/main.py — app assembly: CORS, tracing, middleware install, metrics, router include

See also README “Backend layout (modules)” for a shorter overview.

## HTTP middleware stack (order matters)

Middlewares are installed centrally by core/middleware.install_http_middlewares(app), then the metrics middleware is attached:

1) Size limit — reject bodies over configured bytes to bound memory/CPU
2) Rate limit — in-memory or Redis-backed; updates metrics counter on limit
3) Security headers — X-Content-Type-Options, Referrer-Policy, X-Frame-Options, optional HSTS
4) Request ID — attaches X-Request-ID when absent
5) Concurrency limiter — asyncio.Semaphore to cap in-flight requests; tracks overloads
6) Timeout — wraps handlers in asyncio.wait_for; tracks timeouts
7) Metrics (core/metrics.metrics_middleware) — records count, latency, in-progress, errors

Rationale: quick rejections (size/rate) happen early; safety headers apply consistently; identification via request-id precedes concurrency/timeout controls; metrics observe the post-stack behavior.

## Request lifecycle (contract)

ASGI → middleware stack → router handler → receipts/DB access → response

- Routers are thin: they validate inputs (pydantic models), call into the LatticeDB library, and return typed JSON. Where applicable they update SPD gauges (ΔH, residual).
- Errors are surfaced as HTTPException with clear messages; timeouts/overloads are converted into 503/504 responses by the middlewares.
- The /readyz endpoint performs integrity checks on the DB root and manifest before reporting ready.

## Observability

- /metrics returns Prometheus exposition; it can be header-protected when configured.
- OpenTelemetry tracing can be enabled via settings to emit spans across request handling.

## Determinism contract (expanded)

- Given identical inputs and configuration, the system produces bit-identical indexes and receipts.
- Receipts (lattice and composite) use canonical JSON with stable field ordering and SHA-256 signatures.
- The database Merkle root is computed over lattice state signatures and normalized config; verification checks recompute and compare roots.