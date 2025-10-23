"""
Bench: Notary verify

Loads the DB receipt and verifies a constructed composite against per-lattice receipts
for a fixed selection, returning a summary JSON with verified flag.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict
from urllib import request as _req
from urllib.error import HTTPError as _HTTPError, URLError as _URLError


def _post_json(url: str, payload: Dict[str, Any], timeout: float = 30.0) -> Dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = _req.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with _req.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            return json.loads(body)
    except (_HTTPError, _URLError) as e:
        raise RuntimeError(f"http_error:{url}:{type(e).__name__}:{e}")


def _get_json(url: str, timeout: float = 30.0) -> Dict[str, Any]:
    req = _req.Request(url, method="GET")
    try:
        with _req.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            return json.loads(body)
    except (_HTTPError, _URLError) as e:
        raise RuntimeError(f"http_error:{url}:{type(e).__name__}:{e}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8080")
    ap.add_argument("--db-path", default="latticedb")
    ap.add_argument("--q", default="What is Oscillink?")
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--select", type=int, default=6)
    ap.add_argument("--out", default="_bench/bench_notary_verify.json")
    args = ap.parse_args()

    base = args.url.rstrip("/")
    db_path = str(Path(args.db_path).resolve())
    route_url = base + "/v1/latticedb/route"
    compose_url = base + "/v1/latticedb/compose"
    verify_url = base + "/v1/latticedb/verify"
    dbrec_url = base + "/v1/db/receipt?db_path=" + _quote(db_path)

    try:
        # 1) Route and compose to obtain a fresh composite receipt
        rr = _post_json(route_url, {"db_path": db_path, "q": args.q, "k_lattices": int(args.k)})
        cands = rr.get("candidates", [])
        sel = [str(c.get("lattice_id")) for c in cands[: int(args.select)] if isinstance(c.get("lattice_id"), str)]
        comp = _post_json(compose_url, {"db_path": db_path, "q": args.q, "lattice_ids": sel})
        composite = (comp.get("context_pack", {}).get("receipts", {}) or {}).get("composite")
        if not composite:
            # If compose gated out (epsilon/tau), we still produce a result but mark not verified
            out = {"verified": False, "reason": "no_composite", "selected": sel}
            _write(args.out, out)
            return 0

        # 2) Load ALL lattice receipts from disk so verification can recompute db_root correctly
        lattice_receipts: Dict[str, Dict[str, Any]] = {}
        root = Path(db_path)
        grp = root / "groups"
        if grp.exists():
            for p in grp.glob("**/receipt.json"):
                try:
                    rj = json.loads(p.read_text(encoding="utf-8"))
                    lid = str(rj.get("lattice_id"))
                    if lid:
                        lattice_receipts[lid] = rj
                except Exception:
                    pass

        # 3) Call API verify endpoint
        res = _post_json(verify_url, {"db_path": db_path, "composite": composite, "lattice_receipts": lattice_receipts})
        dbrec = _get_json(dbrec_url)
        out = {"verified": bool(res.get("verified")), "reason": res.get("reason"), "db_root": dbrec.get("db_root"), "selected": sel}
        _write(args.out, out)
        return 0
    except Exception as e:  # noqa: BLE001
        _write(args.out, {"verified": False, "reason": f"exception:{type(e).__name__}:{e}"})
        return 0


def _quote(s: str) -> str:
    from urllib.parse import quote
    return quote(s)


def _write(path: str, obj: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)


if __name__ == "__main__":
    raise SystemExit(main())
