# Benchmarks

This document records the current benchmark results and explains how to run them in this workspace. All commands below assume Windows PowerShell and the provided VS Code tasks. Dates are in UTC.

## Environment

- Date: 2025-10-16
- OS: Windows
- Python: 3.11 (venv at `.venv`)
- API: FastAPI + Uvicorn (dev server)
- Model: bge-small-en-v1.5 (dim=384)
- DB Root: default service path (omit `db_path` unless explicitly aligning with server config)

## How to run

Use the pre-wired tasks (Terminal > Run Task) or run in a PowerShell terminal:

- Install and start API:
  - Task: "Windows: API: Install deps"
  - Task: "Windows: API: Start (dev)" (background)
- Start UI (optional):
  - Task: "Windows: UI: Start (dev)" (background)
- Prepare data (end-to-end suite):
  - Task: "Windows: Assets: Fetch samples"
  - Task: "Windows: Assets: Generate vendor samples"
  - Task: "Windows: Assets: Extract to txt"
  - Task: "Windows: Build lattices (assets_txt)"
- Benchmarks:
  - Task: "Windows: Bench: Query"
  - Task: "Windows: Bench: Scale"
  - Task: "Windows: Bench: Concurrency"
  - Task: "Windows: Bench: Determinism" (or run script without db_path override)

Note: If the API is already running with a configured DB root, avoid passing `--db-path` to bench scripts unless the path matches the API’s configuration.

## Results snapshot

Latest re-run: tasks executed successfully; artifacts updated in `_bench/` and `bench/`.

### Query latency (route + compose)

Source: `_bench/bench_query.json`

- p50 total: 4.12 ms
- p95 total: 5.43 ms
- p50 route: 2.20 ms
- p95 route: 2.55 ms
- p50 compose: 1.95 ms
- p95 compose: 2.85 ms
- n: 10

Notes: On a tiny corpus, CG did not iterate (iters=0) due to guard thresholds selecting 0 lattices in these runs. This reflects routing/overhead more than meaningful composition time.

### Scale sweep (k_lattices)

Source: `_bench/bench_scale.json`

- k=4: p50 4.44 ms, p95 5.88 ms (n=10)
- k=8: p50 4.16 ms, p95 5.49 ms (n=10)

### Concurrency

Source: `bench/concurrency_summary.json`

- submitted: 60
- succeeded: 60, failed: 0, concurrency: 10
- wall: 83.55 s, RPS: 0.718
- p50 total: 14694 ms, p95 total: 16211 ms
- p50 route: 6799 ms, p95 route: 8155 ms
- p50 compose: 7939 ms, p95 compose: 8465 ms

Notes: High latencies under concurrency on this machine and configuration. Further tuning of server concurrency, timeouts, and/or embedding backend may be needed for target SLAs.

### Determinism

Script: `api/scripts/check_determinism.py`

- Invocation (omit db_path override):
  - Result: stable across 10 runs
  - selected: 4
  - unique(deltaH): 1, unique(cg_iters): 1, unique(residual): 1
  - mean deltaH: 3.7820, mean residual: 2.813e-07

Caveat: When forcing a `db_path` that doesn’t match server config, the API may return 500 with non-JSON content. The script was hardened to report these errors instead of crashing.

## Reproducing issues and tips

- If a bench fails with JSONDecodeError: ensure the API is healthy (`GET /health`) and avoid overriding `--db-path` unless necessary.
- For determinism: use the updated script and pass `--timeout 30` to be safe under load.
- For concurrency: capture `/metrics` and server logs during runs; consider adjusting server settings for max concurrency and request timeout.

## Next steps

- Tune concurrency: experiment with server-side concurrency and request timeouts; profile route/compose to identify hotspots.
- Expand scale sweep: include k=12, k=20 once corpus grows and verify CG iterations engage meaningfully.
- Automate benchmark suite: add a CI job that runs query/scale/determinism on a fixed dataset and publishes artifacts.

## Bench run 2025-10-17T03:13:47.704841+00:00

### Query
- total p50: 542.9998500039801 ms; p95: 888.4373999899253 ms (n=10)
- route p50: 529.5423500065226 ms; compose p50: 13.403149991063401 ms

### Scale
- k=4: p50 539.7028000006685 ms; p95 718.0009000003338 ms (n=10)
- k=8: p50 716.3366499880794 ms; p95 832.5859000033233 ms (n=10)
- k=12: p50 717.5993499986362 ms; p95 823.4294000139926 ms (n=10)
- k=20: p50 728.0608500004746 ms; p95 737.0422999956645 ms (n=10)

### Determinism
- stable: True (runs=10, selected=4)
- unique(deltaH): 1, unique(cg_iters): 1, unique(residual): 1

### Concurrency (c=10)
- submitted: 50, succeeded: 50, failed: 0
- total p50: 4460.126400008448 ms; p95: 5068.856800004141 ms; RPS: 2.204553791566061
