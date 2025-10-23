"""
Bench compose latency only: assumes route is fast and just times compose on the top K from a route call.
Outputs _bench/compose_latency.json.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from typing import Any, Dict, List
from urllib import request as _req


def _post_json(url: str, payload: Dict[str, Any], timeout: float = 30.0) -> Dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = _req.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with _req.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="ignore")
        return json.loads(body)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8080")
    ap.add_argument("--runs", type=int, default=100)
    ap.add_argument("--q", default="What is Oscillink?")
    ap.add_argument("--db-path", default=None)
    ap.add_argument("--out", default="_bench/compose_latency.json")
    ap.add_argument("--csv", default=None)
    args = ap.parse_args()

    base = args.url.rstrip("/")
    route_url = base + "/v1/latticedb/route"
    compose_url = base + "/v1/latticedb/compose"

    # Find a fixed selection once to isolate compose cost
    rpayload: Dict[str, Any] = {"q": args.q, "k_lattices": 8}
    if args.db_path:
        rpayload["db_path"] = args.db_path
    rr = _post_json(route_url, rpayload)
    cands = rr.get("candidates", [])
    sel = [str(c.get("lattice_id")) for c in cands[:6] if isinstance(c.get("lattice_id"), str)]

    lat: List[float] = []
    for _ in range(max(1, int(args.runs))):
        payload: Dict[str, Any] = {"q": args.q, "lattice_ids": sel}
        if args.db_path:
            payload["db_path"] = args.db_path
        t0 = time.perf_counter()
        _ = _post_json(compose_url, payload)
        lat.append((time.perf_counter() - t0) * 1000.0)

    p50 = statistics.median(lat) if lat else None
    p95 = (statistics.quantiles(lat, n=100)[94] if len(lat) >= 20 else (max(lat) if lat else None))
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"runs": int(args.runs), "p50_ms": p50, "p95_ms": p95, "min_ms": min(lat) if lat else None, "max_ms": max(lat) if lat else None}, f, indent=2)
    # Optional CSV
    if args.csv:
        try:
            os.makedirs(os.path.dirname(args.csv) or ".", exist_ok=True)
            import csv
            with open(args.csv, "w", newline="", encoding="utf-8") as fcsv:
                w = csv.writer(fcsv)
                w.writerow(["run", "latency_ms"])
                for i, v in enumerate(lat, start=1):
                    w.writerow([i, v])
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
