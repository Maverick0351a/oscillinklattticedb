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