import argparse
import csv
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Sequence

import requests
import sys


def p95(vals: Sequence[float] | Sequence[int]) -> float | None:
    if not vals:
        return None
    idx = max(0, int(0.95 * len(vals)) - 1)
    return sorted(vals)[idx]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_config(db_root: Path) -> Dict[str, Any]:
    cfgp = db_root / "receipts" / "config.json"
    if cfgp.exists():
        try:
            return json.loads(cfgp.read_text())
        except Exception:
            return {}
    return {}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://127.0.0.1:8080")
    p.add_argument("--db-path", default=None)
    p.add_argument("--runs", type=int, default=50)
    p.add_argument("--warmup", type=int, default=5)
    p.add_argument("--q", default="What is Oscillink?")
    p.add_argument("--k-lattices", type=int, default=8)
    p.add_argument("--select", type=int, default=6, help="How many lattices to compose from route candidates")
    p.add_argument("--out", default="_bench/bench_query.json")
    p.add_argument("--csv", default="_bench/bench_query.csv")
    args = p.parse_args()

    base = args.url.rstrip("/")
    sess = requests.Session()

    # Version/git info
    git = {}
    try:
        git = sess.get(f"{base}/version", timeout=5).json()
    except Exception:
        git = {"version": "unknown", "git_sha": "unknown"}

    # Config/model info
    db_root = Path(args.db_path) if args.db_path else Path("latticedb")
    cfg = load_config(db_root)

    # Warmups
    for _ in range(max(0, int(args.warmup))):
        try:
            r = sess.post(f"{base}/v1/latticedb/route", json={"q": args.q, "db_path": str(db_root), "k_lattices": args.k_lattices}, timeout=10)
            cands = r.json().get("candidates", [])
            sel = [c.get("lattice_id") for c in cands[: args.select] if c.get("lattice_id")]
            _ = sess.post(f"{base}/v1/latticedb/compose", json={"q": args.q, "db_path": str(db_root), "lattice_ids": sel}, timeout=10)
        except Exception:
            pass

    lat_total: List[float] = []
    lat_route: List[float] = []
    lat_comp: List[float] = []
    cg_iters: List[int] = []
    cg_resid: List[float] = []
    dH_list: List[float] = []

    rows: List[Dict[str, Any]] = []

    for i in range(int(args.runs)):
        t0 = time.perf_counter()
        r1 = sess.post(
            f"{base}/v1/latticedb/route",
            json={"q": args.q, "db_path": str(db_root), "k_lattices": args.k_lattices},
            timeout=10,
        )
        t1 = time.perf_counter()
        cands = r1.json().get("candidates", [])
        sel = [c.get("lattice_id") for c in cands[: args.select] if c.get("lattice_id")]
        r2 = sess.post(
            f"{base}/v1/latticedb/compose",
            json={"q": args.q, "db_path": str(db_root), "lattice_ids": sel},
            timeout=10,
        )
        t2 = time.perf_counter()
        lat_route.append((t1 - t0) * 1000.0)
        lat_comp.append((t2 - t1) * 1000.0)
        lat_total.append((t2 - t0) * 1000.0)
        try:
            comp = r2.json().get("context_pack", {}).get("receipts", {}).get("composite", {})
            cg_iters.append(int(comp.get("cg_iters", 0)))
            cg_resid.append(float(comp.get("final_residual", 0.0)))
            dH_list.append(float(comp.get("deltaH_total", 0.0)))
        except Exception:
            pass
        rows.append({
            "i": i,
            "route_ms": lat_route[-1],
            "compose_ms": lat_comp[-1],
            "total_ms": lat_total[-1],
            "cg_iters": cg_iters[-1] if len(cg_iters) == len(lat_total) else None,
            "final_residual": cg_resid[-1] if len(cg_resid) == len(lat_total) else None,
            "deltaH_total": dH_list[-1] if len(dH_list) == len(lat_total) else None,
            "selected": len(sel),
        })

    out_dir = Path(args.out).parent
    out_dir.mkdir(parents=True, exist_ok=True)

    header = {
        "schema": 1,
        "commit": git.get("git_sha", "unknown"),
        "date_utc": now_iso(),
        "env": {"python": f"{sys.version_info.major}.{sys.version_info.minor}"} if 'sys' in globals() else {},
        "model": {
            "name": cfg.get("embed_model"),
            "dim": cfg.get("embed_dim"),
            "rev": cfg.get("hf_rev"),
            "weights_sha256": cfg.get("weights_sha256"),
        },
        "params": {
            "k_lattices": args.k_lattices,
            "select": args.select,
        },
        "metrics": {
            "latency_ms": {
                "route_p50": statistics.median(lat_route) if lat_route else None,
                "route_p95": p95(lat_route),
                "compose_p50": statistics.median(lat_comp) if lat_comp else None,
                "compose_p95": p95(lat_comp),
                "total_p50": statistics.median(lat_total) if lat_total else None,
                "total_p95": p95(lat_total),
                "n": len(lat_total),
            },
            "cg": {
                "mean_iters": (sum(cg_iters) / len(cg_iters)) if cg_iters else None,
                "p95_iters": p95(cg_iters) if cg_iters else None,
                "mean_residual": (sum(cg_resid) / len(cg_resid)) if cg_resid else None,
                "mean_deltaH": (sum(dH_list) / len(dH_list)) if dH_list else None,
            },
        },
    }

    # Write JSON
    Path(args.out).write_text(json.dumps({"header": header, "rows": rows}, indent=2))

    # Write CSV
    with Path(args.csv).open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["i","route_ms","compose_ms","total_ms","cg_iters","final_residual","deltaH_total","selected"])
        w.writeheader()
        for r in rows:
            w.writerow(r)

    print(json.dumps({
        "runs": len(lat_total),
        "route_p50_ms": header["metrics"]["latency_ms"]["route_p50"],
        "compose_p50_ms": header["metrics"]["latency_ms"]["compose_p50"],
        "total_p50_ms": header["metrics"]["latency_ms"]["total_p50"],
        "total_p95_ms": header["metrics"]["latency_ms"]["total_p95"],
    }, indent=2))


if __name__ == "__main__":
    main()
