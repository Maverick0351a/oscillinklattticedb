"""
Simple HTTP bench: route -> compose end-to-end latency across N runs.

Writes a JSON summary with p50/p95 and basic stats.
Compatible with the VS Code task: "Windows: Bench: Chat HTTP".
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from typing import Any, Dict, List
from urllib import request as _req
from urllib.error import HTTPError, URLError


def _post_json(url: str, payload: Dict[str, Any], timeout: float = 30.0) -> Dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = _req.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with _req.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="ignore")
        return json.loads(body)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8080", help="Base API URL")
    ap.add_argument("--runs", type=int, default=50)
    ap.add_argument("--q", default="What is Oscillink?")
    ap.add_argument("--db-path", default=None)
    ap.add_argument("--out", default="_bench/bench_chat_http.json")
    args = ap.parse_args()

    base = args.url.rstrip("/")
    route_url = base + "/v1/latticedb/route"
    compose_url = base + "/v1/latticedb/compose"

    latencies: List[float] = []
    errors: List[str] = []

    for i in range(max(1, int(args.runs))):
        payload_route: Dict[str, Any] = {"q": args.q, "k_lattices": 8}
        if args.db_path:
            payload_route["db_path"] = args.db_path
        try:
            t0 = time.perf_counter()
            rr = _post_json(route_url, payload_route)
            cands = rr.get("candidates", [])
            sel = [str(c.get("lattice_id")) for c in cands[:6] if isinstance(c.get("lattice_id"), str)]
            payload_comp: Dict[str, Any] = {"q": args.q, "lattice_ids": sel}
            if args.db_path:
                payload_comp["db_path"] = args.db_path
            _ = _post_json(compose_url, payload_comp)
            dt = time.perf_counter() - t0
            latencies.append(dt)
        except (HTTPError, URLError) as e:
            errors.append(f"http_error:{type(e).__name__}:{e}")
        except Exception as e:  # noqa: BLE001
            errors.append(f"exception:{type(e).__name__}:{e}")

    lat_ms = [x * 1000.0 for x in latencies]
    p50 = statistics.median(lat_ms) if lat_ms else None
    p95 = (statistics.quantiles(lat_ms, n=100)[94] if len(lat_ms) >= 20 else (max(lat_ms) if lat_ms else None))

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(
            {
                "runs": int(args.runs),
                "samples": len(lat_ms),
                "errors": len(errors),
                "p50_ms": p50,
                "p95_ms": p95,
                "min_ms": min(lat_ms) if lat_ms else None,
                "max_ms": max(lat_ms) if lat_ms else None,
            },
            f,
            indent=2,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
