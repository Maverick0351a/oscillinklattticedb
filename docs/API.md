# API

- GET /health → basic health
- GET /livez → liveness probe
- GET /readyz?db_path=<path> → readiness probe with artifact checks
- GET /version → package version and optional git sha
- GET /metrics → Prometheus metrics
- POST /v1/latticedb/ingest → build lattices from input_dir
- POST /v1/latticedb/route → select candidate lattices
- POST /v1/latticedb/compose → composite settle → Context Pack + CompositeReceipt
- POST /v1/latticedb/verify → verify CompositeReceipt (Merkle + config hash)

Auth:

- If JWT is enabled (env: `LATTICEDB_JWT_ENABLED=true`), mutating endpoints (`/v1/latticedb/ingest`, `/v1/latticedb/compose`) require an `Authorization: Bearer <token>` header. Configure secret and options via `LATTICEDB_JWT_SECRET`, `LATTICEDB_JWT_ALGORITHMS` (default HS256), and optional `LATTICEDB_JWT_AUDIENCE` and `LATTICEDB_JWT_ISSUER`.
- If JWT is disabled but API key is required (env: `LATTICEDB_API_KEY_REQUIRED=true`), send `X-API-Key: <key>`.
- Otherwise, these endpoints are open by default (dev convenience).
	- For RS256/IdP integration, set `LATTICEDB_JWT_JWKS_URL` and optionally `LATTICEDB_JWT_LEEWAY` and `LATTICEDB_JWT_CACHE_TTL_SECONDS`. When JWKS is set, it is preferred over shared-secret validation.

Rate limiting (optional):
- Enable basic in-memory per-IP, per-path limits via `LATTICEDB_RATE_LIMIT_ENABLED=true`, with `LATTICEDB_RATE_LIMIT_REQUESTS`/`LATTICEDB_RATE_LIMIT_PERIOD_SECONDS`.
- For multi-instance deployments, set `LATTICEDB_RATE_LIMIT_REDIS_URL=redis://redis:6379/0` to use Redis. Exceeding returns HTTP 429 JSON.

Security and hygiene:
- Security headers: X-Content-Type-Options (nosniff), Referrer-Policy (no-referrer), X-Frame-Options (DENY), and optional HSTS (enable via `LATTICEDB_ENABLE_HSTS=true` when behind TLS).
- Request IDs: accepts `X-Request-ID` or generates one; echoed back on responses.
- Timeouts & concurrency: set `LATTICEDB_REQUEST_TIMEOUT_SECONDS` and `LATTICEDB_MAX_CONCURRENCY` to bound resources; 504/503 on exceed.
- Trust proxy client IP: set `LATTICEDB_TRUST_X_FORWARDED_FOR=true` to key limits by `X-Forwarded-For` (ensure your proxy sets it and is trusted).

Tracing (optional):
- Enable OpenTelemetry by setting `LATTICEDB_OTEL_ENABLED=true`.
- Configure `LATTICEDB_OTEL_EXPORTER_OTLP_ENDPOINT` (default: http://127.0.0.1:4318/v1/traces), `LATTICEDB_OTEL_SERVICE_NAME`, and `LATTICEDB_OTEL_SAMPLE_RATIO`.

Metrics & dashboards:
- Prometheus endpoint at `/metrics`. See `docs/OBSERVABILITY.md` for key series and suggested queries.
- Import `docs/grafana-dashboard.json` in Grafana for a starter dashboard.

Readiness checks include: router_centroids_exists, router_meta_exists, router_meta_readable, db_receipt_exists, config_exists, manifest_exists, config_hash_matches, router_counts_consistent, router_ids_in_manifest.

See inline OpenAPI at /docs when API is running.

Manifest fields (current): group_id, lattice_id, edge_hash, deltaH_total, created_at (ISO8601), source_file, chunk_count, file_bytes, file_sha256.

### Manifest listing

`GET /v1/latticedb/manifest`

Params: db_path, limit, offset, group_id, lattice_id, edge_hash, source_file, min_deltaH, max_deltaH, created_from, created_to, display_name, sort_by (group_id|lattice_id|deltaH_total|display_name), sort_order (asc|desc)

### Manifest search

`GET /v1/latticedb/search`

Params: db_path, q, limit, offset — substring match across group_id, lattice_id, source_file, edge_hash, display_name.

### Lattice metadata

`PUT /v1/latticedb/lattice/{lattice_id}/metadata`

Body: { db_path (optional), display_name }

Notes:
- display_name is user-defined and stored under `db_root/metadata/names.json`.
- This metadata does not affect receipts or the DB Merkle root.

### ACL filters

Opt-in ACL enforcement (env `LATTICEDB_ACL_ENFORCE=1`) lets you scope results by tenant/roles.

Request fields:
- RouteReq: `tenant?: string`, `roles?: string[]`
- ComposeReq: `tenant?: string`, `roles?: string[]`

Behavior:
- When enforcement is on, the server filters candidate lattices where `tenant ∈ acl_tenants` AND `(roles ∩ acl_roles) ≠ ∅` (columns are best-effort; missing columns default to allow). If both tenant and roles are provided, both must pass (AND). If only one is provided, only that rule applies.
- Public content: if a lattice has `acl_public=true` or includes `"public"` in `acl_tenants`, it is allowed regardless of tenant/roles.
- When JWT is enabled, the server can map `tenant` and `roles` from token claims (`tenant`/`org`, `roles`). If enforcement is on and the caller is not privileged (role `admin`), the server ignores client-supplied tenant/roles and uses claims instead.
- When `LATTICEDB_ACL_DENY_ON_MISSING_CLAIMS=1` and enforcement is on, requests without effective tenant/roles are rejected with HTTP 403.
- Compose will abstain when all requested lattices are filtered out: `{ "abstain": true, "reason": "acl_no_candidates" }`.

Examples:

Route

POST /v1/latticedb/route
{
	"db_path": "latticedb",
	"q": "Quarterly results",
	"k_lattices": 12,
	"tenant": "acme",
	"roles": ["analyst", "viewer"]
}

Compose

POST /v1/latticedb/compose
{
	"db_path": "latticedb",
	"q": "Quarterly results",
	"lattice_ids": ["G-000001/L-000007","G-000004/L-000002"],
	"tenant": "acme",
	"roles": ["analyst"]
}