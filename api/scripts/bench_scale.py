import argparse
import json
import statistics
import time
from pathlib import Path
from typing import List

import requests


def p95(vals: List[float]) -> float | None:
    if not vals:
        return None
    idx = max(0, int(0.95 * len(vals)) - 1)
    return sorted(vals)[idx]


def bench_once(base: str, db: str, q: str, k_lattices: int, select: int, runs: int) -> dict:
    sess = requests.Session()
    lat_total: List[float] = []
    for _ in range(runs):
        t0 = time.perf_counter()
        r1 = sess.post(f"{base}/v1/latticedb/route", json={"q": q, "db_path": db, "k_lattices": k_lattices}, timeout=10)
        cands = r1.json().get("candidates", [])
        sel = [c.get("lattice_id") for c in cands[: select] if c.get("lattice_id")]
        _ = sess.post(f"{base}/v1/latticedb/compose", json={"q": q, "db_path": db, "lattice_ids": sel}, timeout=10)
        t1 = time.perf_counter()
        lat_total.append((t1 - t0) * 1000.0)
    return {
        "k_lattices": k_lattices,
        "runs": runs,
        "p50_ms": statistics.median(lat_total) if lat_total else None,
        "p95_ms": p95(lat_total),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8080")
    ap.add_argument("--db-path", default="latticedb")
    ap.add_argument("--q", default="What is Oscillink?")
    ap.add_argument("--select", type=int, default=6)
    ap.add_argument("--runs", type=int, default=50)
    ap.add_argument("--k-grid", default="4,8,12,20")
    ap.add_argument("--out", default="_bench/bench_scale.json")
    args = ap.parse_args()

    base = args.url.rstrip("/")
    db = args.db_path
    ks = [int(x) for x in args.k_grid.split(",") if x.strip()]
    out = []
    for k in ks:
        out.append(bench_once(base, db, args.q, k, args.select, args.runs))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps({"items": out}, indent=2))
    print(json.dumps({"grid": ks, "items": out}, indent=2))


if __name__ == "__main__":
    main()
