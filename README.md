# Oscillink LatticeDB — Local‑First, Verifiable RAG Database

Self‑building, offline RAG you can trust. LatticeDB ingests your documents locally, builds a scalable, semantically sound geometric database, and answers with deterministic receipts and a DB Merkle root so you can verify exactly how every result was produced — no cloud, no third‑party vector DB.

<p align="left">
  <a href="https://github.com/Maverick0351a/oscillinklattticedb/actions/workflows/ci.yml"><img alt="CI" src="https://img.shields.io/github/actions/workflow/status/Maverick0351a/oscillinklattticedb/ci.yml?label=CI"></a>
  <a href="https://app.codecov.io/gh/Maverick0351a/oscillinklattticedb"><img alt="Coverage" src="https://img.shields.io/codecov/c/github/Maverick0351a/oscillinklattticedb?flag=api&label=Coverage"></a>
  <a href="https://github.com/Maverick0351a/oscillinklattticedb/releases"><img alt="Release" src="https://img.shields.io/github/v/release/Maverick0351a/oscillinklattticedb"></a>
  <a href="/LICENSE-LATTICEDB"><img alt="License" src="https://img.shields.io/badge/License-BUSL--1.1-blue"></a>
  <a href="https://github.com/Maverick0351a/oscillinklattticedb/actions/workflows/ci.yml"><img alt="E2E" src="https://img.shields.io/badge/E2E-Playwright-green"></a>
  
</p>

## Why this exists (the problem)

Most “RAG” stacks are:

- Hard to deploy (separate vector DBs, indexers, and glue),
- Not verifiable (no receipts, no audit trail),
- Not truly local‑first (egress or hosted dependencies),
- and noisy (hallucinations with weak provenance).

If you care about security, determinism, and time‑to‑value — especially in air‑gapped or regulated environments — you need a single, offline unit that can organize, retrieve, and prove its answers.

## What this project does (the solution)

Oscillink LatticeDB is a self‑building database for retrieval‑augmented generation:

- Drop documents into a folder; the system ingests (text/PDF/OCR*, Office, CSV/XLSX, HTML, EML/MBOX), chunks, embeds, indexes — all locally.
- Content is organized into micro‑lattices (append‑only). A router picks candidate lattices; a composer runs a fast SPD settle to produce a coherent bundle.
- Every step emits deterministic receipts (hashes, ΔH, CG stats) and a DB Merkle root. You can verify any answer against the database state.
- Offline by default. LLM is optional; extractive answers work out of the box.
- Scales gracefully: small corpora use JSONL; large shards auto‑promote to FAISS with the same deterministic behavior.

*OCR quality is governed by thresholds; low‑confidence scans are down‑ranked or abstained with an explicit reason.*

## Key features

- Self‑building, local‑first: one container/VM, no external DB required.
- Deterministic & auditable: signed receipts + DB Merkle root.
- Geometric, semantically sound retrieval: centroid routing + coherent composition.
- Coherence metrics: exact energy drop (ΔH), CG residuals/iters.
- Guards: OCR quality flags, abstain on weak evidence.
- Ops‑ready: `/health`, `/readyz`, `/metrics`, optional rate limits/JWT.
- UI: minimal chat & receipts modal with “Verify against DB root”.
- Admin metadata and sorting: set human-friendly display names for lattices; filter/sort by display_name in the manifest UI/API with sort-by and asc/desc controls; inline rename available per row in the UI.

## Architecture (at a glance)

```mermaid
flowchart LR
  A[Docs folder] --> I[Ingest: extract → chunk → embed]
  I --> S[Geometric index (micro‑lattices)<br/>+ receipts]
  S --> R[Centroid router (nearest‑K)]
  R --> C[SPD settle (conjugate gradient)<br/>coherent bundle]
  C --> Q[Answer + citations<br/>+ composite receipt]
  S --> M[DB Merkle root]
  Q -. verify .-> M
```

Determinism contract: given the same inputs/config, you get bit‑identical indexes, receipts, and composite decisions.

## Mathematics and technical makeup

We frame retrieval/composition as a well‑posed geometric optimization over a sparse, symmetric positive definite (SPD) system.

- Embedding space and routing
  - Documents are embedded into R^d and organized into micro‑lattices with centroids C ∈ R^{N×d} (float32).
  - Routing selects K candidate lattices via nearest‑centroid search in the same metric space.

- Coherent composition (energy model)
  - Given a working set of K candidates, we solve a convex quadratic to obtain consistent weights x:
    - Minimize E(x) = x^T G x − 2 c^T x + λ_Q ||x||^2, subject to SPD G and small regularization λ_Q.
    - We compute ΔH = E(x_start) − E(x*) as exact energy drop; lower residual and larger ΔH → more coherent bundles.
  - We solve via conjugate gradient (CG), reporting final residual and iteration count for receipts.

- Deterministic receipts and DB root
  - Every stage emits receipts with: ΔH, CG iterations/residual, edge hashes, and configuration hashes.
  - A Merkle root over lattice receipts + config produces the DB root; composite receipts verify against this root.

- Data shapes (contract)
  - Centroids: N×d float32 (router/centroids.f32) with meta.parquet describing lattice_id ordering.
  - Manifest: Parquet table with group_id, lattice_id, edge_hash, deltaH_total, created_at, source_file, …
  - Receipts: JSON (per‑lattice and composite) with stable field ordering and SHA‑256 signatures.
  - Metadata: Optional display_name mapping at metadata/names.json (does not affect cryptographic roots).

## Quickstart (local, minimal)

These commands are illustrative — adjust paths/scripts to your repo.

### Start the API

```bash
# create venv, install dev deps, run API
python -m venv .venv && source .venv/bin/activate
pip install -e .[dev]
uvicorn app.main:app --host 127.0.0.1 --port 8080
```

### (Optional) Start the UI

```bash
cd ui
npm install
npm run dev
# open the printed localhost URL
```

### Build the database

```bash
# fetch or point to a docs folder; then ingest
python scripts/build_lattices.py --input ./sample_docs --out ./latticedb
```

### Check readiness & DB receipt

```bash
curl 'http://127.0.0.1:8080/readyz?db_path=./latticedb'
curl 'http://127.0.0.1:8080/v1/db/receipt' | jq
```

### Ask a question

```bash
python scripts/query.py --db ./latticedb --q "Summarize the indemnity clause"
# or use the UI: ask, then open "Receipts…" and click "Verify"
```

Tip: The watcher can run in the background so dropping files triggers ingest automatically.

Tip: To label a lattice with a friendly name, call:

```powershell
Invoke-RestMethod -Method Put -Uri "http://127.0.0.1:8080/v1/latticedb/lattice/<LATTICE_ID>/metadata" -ContentType 'application/json' -Body (@{ db_path = "./latticedb"; display_name = "My Contract" } | ConvertTo-Json)
```
Then reload the manifest in the UI; you can also sort by display_name (and choose asc/desc) via the UI or API.

## Benchmarks that matter (and how to run)

Reproducible scripts live in `api/scripts` and write artifacts under `_bench/` (and some to `bench/`) so CI can archive and you can graph over time. A quick subset also runs in CI via the “Bench Suite” workflow and uploads artifacts.

- Determinism (gating check): `python api/scripts/check_determinism.py --url http://127.0.0.1:8080 --db-path latticedb --q "What is Oscillink?" --k-lattices 8 --select 6 --runs 5`
- Query micro-bench (route→compose with warmup): `python api/scripts/bench_query.py --url http://127.0.0.1:8080 --db-path latticedb --runs 50 --warmup 5 --q "What is Oscillink?" --k-lattices 8 --select 6 --out _bench/bench_query.json --csv _bench/bench_query.csv`
- Scale curve: `python api/scripts/bench_scale.py --url http://127.0.0.1:8080 --db-path latticedb --q "What is Oscillink?" --select 6 --runs 50 --k-grid 4,8,12,20 --out _bench/bench_scale.json`
- HTTP route→compose latency (simple): `python api/scripts/bench_http.py --url http://127.0.0.1:8080 --runs 50 --q "What is Oscillink?"` (writes `bench/summary.json`)
- Concurrency: `python api/scripts/bench_concurrency.py --url http://127.0.0.1:8080 --runs 200 --concurrency 20 --q "What is Oscillink?"`
- OCR quality (stub): `python api/scripts/bench_ocr_quality.py --labels-csv bench/assets/ocr_labels.csv --out _bench/bench_ocr_quality.json`

## Test coverage

We keep tight, deterministic tests around the FastAPI service in `api/app/main.py` and gate PRs at 95% line coverage (branch coverage enabled).

- In VS Code: run the task “API: Coverage (HTML)”. It executes the suite under coverage and writes a browsable report to `api/coverage_html/index.html`.
- CLI (Windows PowerShell):

```powershell
Set-Location "api"; python -m pip install -U pip; pip install -e .[dev]; `
coverage run -m pytest; coverage report; coverage html
# Open the report
Start-Process .\coverage_html\index.html
```

- CLI (macOS/Linux):

```bash
cd api
python -m pip install -U pip
pip install -e .[dev]
coverage run -m pytest
coverage report
coverage html
open coverage_html/index.html  # macOS
xdg-open coverage_html/index.html  # Linux
```

In CI, we enforce `coverage report --fail-under=95` and upload the HTML report as an artifact for inspection.

UI coverage scope: The UI job reports coverage for UI source code only (unit tests via Vitest + jsdom). It does not imply runtime coverage of API features, bench scripts, or the ingestion pipeline. For full-stack validation, see the E2E job which runs Playwright against a live API and uploads an HTML report and traces as artifacts.

Artifacts to expect on CI runs:
- ui-coverage: Vitest coverage report for UI unit tests
- e2e-playwright-report: HTML report for UI E2E tests
- e2e-test-results: Playwright traces/videos for failures

## Bring your own models (BYOM)

We don’t bundle adapters or force a specific model. You can:

- LLM (generation): enable an on-device runtime (recommended: Ollama) and point the API at your model.
  - Set environment variables and start the API with LLM enabled:

```powershell
# Example with Ollama and mistral as the starting model
$env:LATTICEDB_LLM_ENABLED = "1"
$env:LATTICEDB_LLM_BACKEND = "ollama"   # current scaffold supports ollama
$env:LATTICEDB_LLM_ENDPOINT = "http://127.0.0.1:11434"
$env:LATTICEDB_LLM_MODEL = "mistral"     # bring your own: any model you've pulled into Ollama
```

  - Then call `POST /v1/latticedb/chat` to compose context and generate an answer. We don’t attach adapters; if your model needs LoRA or similar, attach it within your Ollama model setup.

- Embeddings (retrieval): use our presets or specify a HuggingFace model id directly without editing the registry.
  - Anywhere you can pass `embed_model` (ingest, route, scan), you can provide:
    - a known preset id like `bge-small-en-v1.5`, or
    - a direct HF id like `intfloat/e5-small-v2` (or prefix with `hf:intfloat/e5-small-v2`).
  - The scaffold will load the model from HF locally (if available) or use a deterministic stub if transformers/weights aren’t present. No adapters are applied by default.

Notes:
- Consistency: For best verification properties, keep the same embedding model during ingest and query. The DB receipt records the chosen `embed_model` and hashes when available.
- Security: The scaffold is offline by default. If you allow egress to download models, do so explicitly and pin revisions/hashes for reproducibility.

### Default LLM with an adapter (Ollama)

We keep the runtime simple and do not attach adapters in code. For the default path, you can still attach an adapter by creating an Ollama model that wraps the base model with your adapter, then point the API at that model name.

1) Create a Modelfile (example) that references your base and adapter:

```
# Modelfile: mistral-lattice
FROM mistral
# Replace with your adapter reference; can be a local path or an adapter in your Ollama store
ADAPTER ./adapters/my_mistral_lora
PARAMETER temperature 0
PARAMETER top_p 1
```

2) Build it in Ollama (example):

```powershell
ollama create mistral-lattice -f .\Modelfile
```

3) Point LatticeDB at your adapter-wrapped model:

```powershell
$env:LATTICEDB_LLM_ENABLED = "1"
$env:LATTICEDB_LLM_BACKEND = "ollama"
$env:LATTICEDB_LLM_ENDPOINT = "http://127.0.0.1:11434"
$env:LATTICEDB_LLM_MODEL = "mistral-lattice"
```

That attaches an adapter for the default experience without coupling our code to a specific adapter system. Clients bringing other models/adapters can create their own Ollama model names the same way and set `LATTICEDB_LLM_MODEL` accordingly.

## Licensing

This repository is provided under the Business Source License 1.1 (BUSL-1.1). See `LICENSE-LATTICEDB` for the full terms and Additional Use Grant.

- Change Date: 2029-10-16, after which the license converts to MIT for covered files.
- SPDX identifier to use in headers: `BUSL-1.1`.

If you have specific licensing or usage questions, please open an issue.
