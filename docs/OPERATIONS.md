# Operations

- Append-only store; single writer (ingest) with atomic dir rename; many readers.
- Determinism mode is default.
- OCR is optional (not enabled in scaffold). Hook in later as a sidecar worker.

## Authentication & rate limiting

- Prefer JWT Bearer for production:
	- Configure via env: `LATTICEDB_JWT_ENABLED=true`, set `LATTICEDB_JWT_SECRET` (or use KMS/secret store).
	- Optionally configure audience/issuer; rotate secrets regularly.
	- Proxies must forward `Authorization` header.
- API key fallback:
	- `LATTICEDB_API_KEY_REQUIRED=true` and set `LATTICEDB_API_KEY`.
	- Suitable for internal tools or simple deployments; rotate keys periodically.
- Rate limiting:
	- Built-in in-memory limiter is per-IP and per-path; enable with `LATTICEDB_RATE_LIMIT_ENABLED=true`.
	- For multi-instance deployments, use a shared backend (e.g., Redis) or enforce limits at the gateway.
- Real client IP:
	- If running behind a reverse proxy or load balancer, ensure `X-Forwarded-For` is set and trusted, or enforce limiting at the edge.

## ACL enforcement

- Enable with `LATTICEDB_ACL_ENFORCE=1` to activate tenant/roles filtering.
- Optional strict posture: `LATTICEDB_ACL_DENY_ON_MISSING_CLAIMS=1` returns 403 when enforcement is on and no tenant/roles claims are present.
- Mapping from JWT to ACL (optional):
	- `tenant` from `claims["tenant"]` or `claims["org"]`
	- `roles` from `claims["roles"]` (array)
- When enforcement is on and the caller is not privileged (role `admin`), client-provided `tenant`/`roles` fields are ignored and the server uses the JWT claims instead.
- Readiness includes an informational ratio `acl_columns_present_ratio` when enabled; missing ACL columns default to allow but emit warnings.
- Metrics:
	- `latticedb_acl_filtered_candidates_total{endpoint="route|compose"}`
	- `latticedb_acl_abstain_total{reason="acl_no_candidates"}`

Public content:
- World-readable content can be tagged with `acl_public=true` or adding `"public"` to `acl_tenants`; such lattices are allowed regardless of tenant/roles.
  (When `LATTICEDB_ACL_DENY_ON_MISSING_CLAIMS=1`, this does not bypass the global 403 at the route/compose level; switch to a "public-only" mode as a future option if needed.)

## Readiness and Liveness

### Probes

- Liveness: `GET /livez` (always cheap)
- Readiness (fast path): `GET /readyz?summary=true`
	- Uses inode/existence checks only. Suitable for container/orchestrator healthchecks.
- Readiness (deep/strict): `GET /readyz?strict=true`
	- Validates receipts, hashes, schema version, router integrity. Use on deploy, cron, or synthetic canaries.

Optional: enable a small TTL cache for strict readiness to avoid expensive bursts under load.

Environment variable:

```
LATTICEDB_READYZ_STRICT_TTL_SECONDS=5
```

When set (> 0), strict readiness responses are cached for the TTL window. Summary readiness is never cached.

### DB Root Configuration

`LATTICEDB_DB_ROOT` must be absolute. Windows paths are supported.

Examples:

```
# Windows PowerShell
$env:LATTICEDB_DB_ROOT="C:\\Users\\<you>\\path\\to\\latticedb"

# Linux/macOS
export LATTICEDB_DB_ROOT="/workspace/latticedb"
```

You can also place this in `api/.env` for local development.

### Docker Compose healthcheck

```
services:
	api:
		environment:
			- LATTICEDB_DB_ROOT=${LATTICEDB_DB_ROOT}
		healthcheck:
			test: ["CMD", "curl", "-fsS", "http://127.0.0.1:8080/readyz?summary=true"]
			interval: 15s
			timeout: 2s
			retries: 5
			start_period: 20s
```

### CI Gate (strict)

```
python api/scripts/readyz_report.py --url http://127.0.0.1:8080 --db-path latticedb --strict --schema-limit 50
```

## Cache management (admin)

Two admin-protected ops hooks let you clear in-process caches or force a router remap without restarting the API. These reuse the existing metrics protection secret; set `LATTICEDB_METRICS_PROTECTED=1` and `LATTICEDB_METRICS_SECRET=...`.

- POST `/v1/ops/caches/clear`
	- Clears: ManifestCache and the memmap LRU (centroids)
	- Header required: `X-Admin-Secret: <metrics_secret>`
	- Response: `{ "ok": true, "cleared": ["manifest", "mmap"] }`

- POST `/v1/ops/router/reload`
	- Clears the memmap LRU so the next request remaps `router/centroids.*`
	- Header required: `X-Admin-Secret: <metrics_secret>`
	- Response: `{ "ok": true, "action": "router_mmap_cleared" }`

When to use:
- After heavy ingest/promotions when you want to reclaim RSS on Windows
- After toggling performance flags to ensure a fresh mapping
