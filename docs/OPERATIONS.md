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