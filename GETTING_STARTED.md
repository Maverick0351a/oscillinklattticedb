# Getting Started

1. Open this folder in VS Code.
2. Run the task "API: Start (dev)" (Ctrl/Cmd+Shift+P -> "Tasks: Run Task").
3. Run the task "UI: Start (dev)".
4. In a terminal: `python api/scripts/build_lattices.py --input sample_data/docs --out latticedb`
5. Visit the UI and ask: "What is Oscillink?" — open the Receipts modal; click Verify.

Probes and metrics:

- Readiness: GET http://127.0.0.1:8080/readyz?db_path=latticedb
- Liveness: GET http://127.0.0.1:8080/livez
- Metrics (Prometheus): GET http://127.0.0.1:8080/metrics

Observability stack (optional):

- Start Prometheus and Grafana (separate compose file):
	- docker compose -f docker-compose.observability.yml up
	- Prometheus: http://127.0.0.1:9090
	- Grafana: http://127.0.0.1:3000 (admin/admin)
		- Import `docs/grafana-dashboard-api-http.json` via Grafana UI (Dashboards → Import)

This scaffold ships deterministic stubs so you can test the flow end-to-end before you swap in
the full Oscillink solver. All receipts/merkle logic is real.

## Fetch sample assets (Windows/macOS/Linux)

We include a tiny, reproducible asset fetcher that downloads a few sample files with optional SHA-256 verification.

1. Review or edit the manifest at `bench/assets/manifest.yml`. Leave `sha256: null` for new files.
2. Run the fetcher (PowerShell or any shell from repo root):

```powershell
# Windows (PowerShell)
python api/scripts/fetch_samples.py
```

```bash
# macOS/Linux
python api/scripts/fetch_samples.py
```

3. The script prints computed hashes for entries with `sha256: null`. Paste those back into the manifest to pin integrity.

4. Ingest the fetched assets (they land under `bench/assets/...`):

```powershell
python api/scripts/build_lattices.py --input bench/assets --out latticedb
```

Notes
- Dependencies are included in the dev extras (`pooch`, `PyYAML`). Install with: `pip install -e api[dev]`.
- There’s a VS Code task: “Windows: Assets: Fetch samples” that runs the same script with the venv activated.

### Optional: Extract to text and ingest

Some formats (PDF, DOCX, CSV) can be converted to plain text first to improve chunking and consistency. We provide a helper:

1. Extract text from the downloaded assets into `sample_data/assets_txt`:

```powershell
# Windows (PowerShell)
python api/scripts/extract_assets.py --manifest bench/assets/manifest.yml --out-dir sample_data/assets_txt
```

```bash
# macOS/Linux
python api/scripts/extract_assets.py --manifest bench/assets/manifest.yml --out-dir sample_data/assets_txt
```

2. Build lattices from the extracted text directory:

```powershell
python api/scripts/build_lattices.py --input sample_data/assets_txt --out latticedb
```

There are VS Code tasks for these steps:

- "Windows: Assets: Extract to txt"
- "Windows: Build lattices (assets_txt)"

### Benchmarks and determinism

- Quick latency bench: "Windows: Bench: Query" (writes `_bench/bench_query.json/.csv`)
- Scale sweep: "Windows: Bench: Scale"
- Concurrency: "Windows: Bench: Concurrency"
- Determinism check: "Windows: Bench: Determinism" (repeats compose on a fixed selection and checks that receipts fields are stable)

To run the whole flow end-to-end: "Windows: Bench: End-to-End Suite" (fetch → extract → build → query → scale → ocr-stub → determinism)

## Auth and rate limiting

- For local dev, auth is open by default. For production, enable ONE of:
	- JWT Bearer: set `LATTICEDB_JWT_ENABLED=true` and `LATTICEDB_JWT_SECRET` (optionally audience/issuer). Send `Authorization: Bearer <token>` for mutating endpoints (`/v1/latticedb/ingest`, `/v1/latticedb/compose`).
	- API key: set `LATTICEDB_API_KEY_REQUIRED=true` and `LATTICEDB_API_KEY=<key>`, then send `X-API-Key: <key>`.

Optional: enable in-memory rate limiting with `LATTICEDB_RATE_LIMIT_ENABLED=true` and adjust `LATTICEDB_RATE_LIMIT_REQUESTS` / `LATTICEDB_RATE_LIMIT_PERIOD_SECONDS`.