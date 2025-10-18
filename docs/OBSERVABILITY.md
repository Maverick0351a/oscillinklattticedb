# Observability

This service exposes Prometheus metrics and can optionally publish OpenTelemetry traces.

## Metrics

- Endpoint: `GET /metrics` (Prometheus text format)
- Key series (labels omitted for brevity):
  - `http_requests_total{method,path,status}`: Request counter
  - `http_request_duration_seconds_bucket|sum|count{method,path}`: Latency histogram (predefined buckets from 5ms to 10s)
  - `http_inprogress_requests`: In-flight requests gauge
  - `http_requests_errors_total{method,path,status}`: 5xx responses
  - `http_request_timeouts_total{path}`: 504 timeouts
  - `http_requests_overload_total{path}`: 503 rejections due to max concurrency
  - `http_rate_limited_total{path}`: 429 rate-limited responses

Suggested Prometheus recording rules:

- p95 latency per route:
  `histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le, path))`
- Error rate:
  `sum(rate(http_requests_errors_total[5m])) by (path)`

## Tracing (optional)

Enable tracing with environment variables:

- `LATTICEDB_OTEL_ENABLED=true`
- `LATTICEDB_OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318/v1/traces`
- `LATTICEDB_OTEL_SERVICE_NAME=latticedb-api`
- `LATTICEDB_OTEL_SAMPLE_RATIO=0.1` (10% sampling)

Then point your OpenTelemetry Collector to a backend (Tempo, Jaeger, Azure Monitor, etc.).

## Grafana: minimal dashboard

Import `docs/grafana-dashboard.json` into Grafana to get a basic view of latency (p50/p95), request rate, and errors by path.
