"""SPDX-License-Identifier: BUSL-1.1"""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BENCH_DIR = ROOT / "_bench"
DOC = ROOT / "benchmark.md"


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def append_markdown(block: str) -> None:
    DOC.parent.mkdir(parents=True, exist_ok=True)
    with DOC.open("a", encoding="utf-8") as f:
        f.write("\n" + block.strip() + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description="Run query/scale/determinism benches and append to benchmark.md")
    ap.add_argument("--url", default="http://127.0.0.1:8080")
    ap.add_argument("--q", default="What is Oscillink?")
    ap.add_argument("--k-lattices", type=int, default=8)
    ap.add_argument("--select", type=int, default=6)
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--with-concurrency", action="store_true")
    args = ap.parse_args()

    BENCH_DIR.mkdir(exist_ok=True)

    # Run Query bench
    bq_out = BENCH_DIR / "bench_query.json"
    bq_csv = BENCH_DIR / "bench_query.csv"
    cmd_query = [
        sys.executable,
        str(ROOT / "api" / "scripts" / "bench_query.py"),
        "--url", args.url,
        "--runs", str(args.runs),
        "--warmup", "5",
        "--q", args.q,
        "--k-lattices", str(args.k_lattices),
        "--select", str(args.select),
        "--out", str(bq_out),
        "--csv", str(bq_csv),
    ]
    rq = run(cmd_query)

    # Run Scale bench (k grid)
    bs_out = BENCH_DIR / "bench_scale.json"
    cmd_scale = [
        sys.executable,
        str(ROOT / "api" / "scripts" / "bench_scale.py"),
        "--url", args.url,
        "--q", args.q,
        "--select", str(args.select),
        "--runs", str(args.runs),
        "--k-grid", "4,8,12,20",
        "--out", str(bs_out),
    ]
    rs = run(cmd_scale)

    # Determinism (omit db_path override)
    cmd_det = [
        sys.executable,
        str(ROOT / "api" / "scripts" / "check_determinism.py"),
        "--url", args.url,
        "--q", args.q,
        "--k-lattices", str(args.k_lattices),
        "--select", str(args.select),
        "--runs", str(args.runs),
        "--timeout", str(args.timeout),
    ]
    rd = run(cmd_det)

    # Optional: concurrency bench (summary file is written by its own script)
    rc_sum = None
    if args.with_concurrency:
        cmd_conc = [
            sys.executable,
            str(ROOT / "api" / "scripts" / "bench_concurrency.py"),
            "--url", args.url,
            "--runs", str(max(50, args.runs * 5)),
            "--concurrency", "10",
            "--q", args.q,
        ]
        run(cmd_conc)
        # Attempt to read standard summary file if produced
        conc_file = ROOT / "bench" / "concurrency_summary.json"
        if conc_file.exists():
            try:
                rc_sum = json.loads(conc_file.read_text(encoding="utf-8"))
            except Exception:
                rc_sum = None

    # Load results
    now = datetime.now(timezone.utc).isoformat()

    q = None
    try:
        q = json.loads(bq_out.read_text(encoding="utf-8"))
    except Exception:
        q = None

    s = None
    try:
        s = json.loads(bs_out.read_text(encoding="utf-8"))
    except Exception:
        s = None

    d = None
    try:
        d = json.loads(rd.stdout)
    except Exception:
        d = None

    # Build markdown block
    lines: list[str] = []
    lines.append(f"## Bench run {now}")
    lines.append("")
    # Query
    if q and "header" in q and "metrics" in q["header"] and "latency_ms" in q["header"]["metrics"]:
        lm = q["header"]["metrics"]["latency_ms"]
        lines.append("### Query")
        lines.append(f"- total p50: {lm.get('total_p50')} ms; p95: {lm.get('total_p95')} ms (n={lm.get('n')})")
        lines.append(f"- route p50: {lm.get('route_p50')} ms; compose p50: {lm.get('compose_p50')} ms")
        lines.append("")
    else:
        lines.append("### Query")
        lines.append(f"- FAILED (exit={rq.returncode})\n")

    # Scale
    if s and "items" in s:
        lines.append("### Scale")
        for item in s["items"]:
            lines.append(f"- k={item.get('k_lattices')}: p50 {item.get('p50_ms')} ms; p95 {item.get('p95_ms')} ms (n={item.get('runs')})")
        lines.append("")
    else:
        lines.append("### Scale")
        lines.append(f"- FAILED (exit={rs.returncode})\n")

    # Determinism
    if d and isinstance(d, dict):
        lines.append("### Determinism")
        lines.append(f"- stable: {d.get('stable')} (runs={d.get('runs')}, selected={d.get('selected')})")
        lines.append(f"- unique(deltaH): {d.get('deltaH_unique')}, unique(cg_iters): {d.get('cg_iters_unique')}, unique(residual): {d.get('residual_unique')}")
        lines.append("")
    else:
        lines.append("### Determinism")
        lines.append(f"- FAILED (exit={rd.returncode})\n")

    # Concurrency (optional)
    if args.with_concurrency:
        lines.append("### Concurrency (c=10)")
        if rc_sum:
            lines.append(f"- submitted: {rc_sum.get('submitted')}, succeeded: {rc_sum.get('succeeded')}, failed: {rc_sum.get('failed')}")
            lines.append(f"- total p50: {rc_sum.get('p50_ms')} ms; p95: {rc_sum.get('p95_ms')} ms; RPS: {rc_sum.get('rps')}")
            lines.append("")
        else:
            lines.append("- FAILED or no summary found\n")

    append_markdown("\n".join(lines))

    # Return non-zero if any core bench failed
    failed = 0
    if not q:
        failed += 1
    if not s:
        failed += 1
    if not d:
        failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
