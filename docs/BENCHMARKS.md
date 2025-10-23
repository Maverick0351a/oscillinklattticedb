# Benchmarks

Run:
  python api/scripts/bench_http.py --url http://127.0.0.1:8080 --runs 100 --q "What is Oscillink?"

Writes bench/summary.json (p50/p95). Targets (scaffold):
- Route+Compose p50 <= 120 ms; p95 <= 200 ms (CPU, warm).

Additional scripts:

- Route-only:

  python api/scripts/bench_route.py --url http://127.0.0.1:8080 --runs 100 --q "What is Oscillink?"

- Compose-only (routes first to pick IDs):

  python api/scripts/bench_compose.py --url http://127.0.0.1:8080 --runs 100 --q "What is Oscillink?"

- Concurrency sweep with k6 (optional):

  k6 run bench/k6_route_compose.js --env URL=http://127.0.0.1:8080 --env Q="What is Oscillink?" --vus 10 --duration 30s

## Performance Tuning (quick wins)

- Use multiple workers for API:
  - Windows dev: `uvicorn app.main:app --host 127.0.0.1 --port 8080 --workers 4`
  - Linux/container: `gunicorn -k uvicorn.workers.UvicornWorker -w 4 app.main:app`

- Readiness probes:
  - Use `GET /readyz?summary=true` for orchestrator healthchecks (cheap)
  - Reserve `GET /readyz?strict=true` for deploy/canary validation

- Enable strict readiness TTL cache to avoid bursts:
  - `LATTICEDB_READYZ_STRICT_TTL_SECONDS=5`

- Optional toggles (future):
  - `LATTICEDB_MANIFEST_CACHE=1` to keep manifest in memory with TTL/invalidation
  - `LATTICEDB_MMAP_ENABLED=1` to memory-map large `.npy` arrays for router/embeds
  - `LATTICEDB_MANIFEST_CACHE_TTL_SECONDS=60` to set manifest cache TTL
  - `LATTICEDB_MMAP_LRU_CAP=8` to control mmap LRU size
  - `LATTICEDB_READYZ_STRICT_TTL_SECONDS=5` for strict readiness caching

- Benchmarks to compare:
  - Dev server baseline: `python api/scripts/bench_concurrency.py --runs 50 --concurrency 10 --out _bench/concurrency_dev.json`
  - Workers=4: `python api/scripts/bench_concurrency.py --runs 50 --concurrency 10 --out _bench/concurrency_w4.json`

### Concurrency checklist

- Use workers=4 (CPU-bound routing/compose is cheap and scales well)
- Enable manifest cache and mmap for laptops via env:

```
LATTICEDB_MANIFEST_CACHE=1
LATTICEDB_MANIFEST_CACHE_TTL_SECONDS=60
LATTICEDB_MMAP_ENABLED=1
LATTICEDB_MMAP_LRU_CAP=8
LATTICEDB_READYZ_STRICT_TTL_SECONDS=5
```

Targets (modern laptop, c=10): p50 ≤ ~750 ms, p95 ≤ ~1.5 s