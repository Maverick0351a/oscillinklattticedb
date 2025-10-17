import argparse
import concurrent.futures as cf
import json
import statistics
import time
import threading
from pathlib import Path

import requests


def do_one(session: requests.Session, base_url: str, q: str, timeout: float):
    t0 = time.perf_counter()
    r1 = session.post(f"{base_url}/v1/latticedb/route", json={"q": q}, timeout=timeout)
    rt1 = time.perf_counter()
    r1.raise_for_status()
    cands = r1.json().get("candidates", [])
    sel = [c.get("lattice_id") for c in cands[:3] if c.get("lattice_id") is not None]
    r2 = session.post(
        f"{base_url}/v1/latticedb/compose",
        json={"q": q, "lattice_ids": sel},
        timeout=timeout,
    )
    rt2 = time.perf_counter()
    r2.raise_for_status()
    total_ms = (rt2 - t0) * 1000.0
    route_ms = (rt1 - t0) * 1000.0
    compose_ms = (rt2 - rt1) * 1000.0
    return total_ms, route_ms, compose_ms


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://127.0.0.1:8080")
    p.add_argument("--runs", type=int, default=200)
    p.add_argument("--concurrency", type=int, default=20)
    p.add_argument("--q", default="What is Oscillink?")
    p.add_argument("--timeout", type=float, default=10.0, help="Per-request timeout in seconds")
    args = p.parse_args()

    lat_total = []
    lat_route = []
    lat_comp = []
    failures = 0

    start_wall = time.perf_counter()
    with cf.ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        # Use thread-local storage to reuse a Session per worker
        tls = threading.local()

        def get_session() -> requests.Session:
            sess = getattr(tls, "session", None)
            if sess is None:
                sess = requests.Session()
                tls.session = sess
            return sess

        def task(_):
            sess = get_session()
            try:
                return do_one(sess, args.url, args.q, args.timeout)
            except Exception:
                return None

        futures = [ex.submit(task, i) for i in range(args.runs)]
        for fut in cf.as_completed(futures):
            res = fut.result()
            if res is None:
                failures += 1
            else:
                t_ms, r_ms, c_ms = res
                lat_total.append(t_ms)
                lat_route.append(r_ms)
                lat_comp.append(c_ms)
    end_wall = time.perf_counter()

    wall_s = end_wall - start_wall
    succeeded = len(lat_total)
    submitted = args.runs
    rps = succeeded / wall_s if wall_s > 0 else None

    def p95(vals):
        if not vals:
            return None
        idx = max(0, int(0.95 * len(vals)) - 1)
        return sorted(vals)[idx]

    summary = {
        "submitted": submitted,
        "succeeded": succeeded,
        "failed": failures,
        "concurrency": args.concurrency,
        "wall_s": wall_s,
        "rps": rps,
        "p50_ms": statistics.median(lat_total) if lat_total else None,
        "p95_ms": p95(lat_total),
        "p50_route_ms": statistics.median(lat_route) if lat_route else None,
        "p95_route_ms": p95(lat_route),
        "p50_compose_ms": statistics.median(lat_comp) if lat_comp else None,
        "p95_compose_ms": p95(lat_comp),
    }

    Path("bench").mkdir(exist_ok=True, parents=True)
    Path("bench/concurrency_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
