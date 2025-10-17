import argparse
import json
import statistics
from typing import Any, Dict, List

import requests


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8080")
    ap.add_argument("--db-path", default=None, help="Optional DB path override for the API; omit to use server default")
    ap.add_argument("--q", default="What is Oscillink?")
    ap.add_argument("--k-lattices", type=int, default=8)
    ap.add_argument("--select", type=int, default=6)
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--timeout", type=float, default=30.0, help="Per-request timeout seconds")
    args = ap.parse_args()

    base = args.url.rstrip("/")
    sess = requests.Session()

    # Fixed route selection by first run
    route_payload = {"q": args.q, "k_lattices": args.k_lattices}
    if args.db_path:
        route_payload["db_path"] = args.db_path
    r = sess.post(
        f"{base}/v1/latticedb/route",
        json=route_payload,
        timeout=args.timeout,
    )
    try:
        cands = r.json().get("candidates", [])
    except Exception:
        # Fall back to empty if non-JSON (e.g., 502/timeout proxy page)
        cands = []
    sel = [c.get("lattice_id") for c in cands[: args.select] if c.get("lattice_id")]

    receipts: List[Dict[str, Any]] = []
    dH: List[float] = []
    iters: List[int] = []
    resid: List[float] = []
    errors: List[str] = []
    for i in range(args.runs):
        try:
            compose_payload = {"q": args.q, "lattice_ids": sel}
            if args.db_path:
                compose_payload["db_path"] = args.db_path
            c = sess.post(
                f"{base}/v1/latticedb/compose",
                json=compose_payload,
                timeout=args.timeout,
            )
        except Exception as e:
            errors.append(f"request_error_run_{i}: {type(e).__name__}: {e}")
            continue
        try:
            comp = c.json().get("context_pack", {}).get("receipts", {}).get("composite", {})
        except Exception as e:
            errors.append(f"json_error_run_{i}: status={c.status_code} body_len={len(c.text) if hasattr(c, 'text') else 'na'} err={type(e).__name__}: {e}")
            continue
        receipts.append(comp)
        dH.append(float(comp.get("deltaH_total", 0.0)))
        iters.append(int(comp.get("cg_iters", 0)))
        resid.append(float(comp.get("final_residual", 0.0)))

    stable = (
        len(set(round(x, 8) for x in dH)) == 1
        and len(set(iters)) == 1
        and len(set(round(x, 8) for x in resid)) == 1
        and not errors
    )

    out = {
        "runs": args.runs,
        "selected": len(sel),
        "deltaH_unique": len(set(round(x, 12) for x in dH)),
        "cg_iters_unique": len(set(iters)),
        "residual_unique": len(set(round(x, 12) for x in resid)),
        "stable": stable,
        "deltaH_mean": statistics.mean(dH) if dH else None,
        "residual_mean": statistics.mean(resid) if resid else None,
        "succeeded": len(receipts),
        "failed": len(errors),
        "errors": errors,
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
