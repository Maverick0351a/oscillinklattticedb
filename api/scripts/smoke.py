from __future__ import annotations

import json
import sys
from pathlib import Path

from latticedb.ingest import ingest_dir
from latticedb.merkle import merkle_root
from latticedb.router import Router
from latticedb.composite import composite_settle


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("latticedb")
    data = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).resolve().parents[2] / "sample_data" / "docs"

    print(f"[smoke] ingesting from {data} -> {root}")
    recs = ingest_dir(data, root)
    if not recs:
        print("[smoke] no receipts produced", file=sys.stderr)
        return 2
    leaves = [r.state_sig for r in recs]
    cfg_path = root / "receipts" / "config.json"
    cfg_hash = (cfg_path.read_bytes() if cfg_path.exists() else b"stub")
    db_root = merkle_root(leaves + [merkle_root([cfg_hash.hex()])])
    (root / "receipts").mkdir(parents=True, exist_ok=True)
    (root / "receipts" / "db_receipt.json").write_text(
        json.dumps({"version": "1", "db_root": db_root, "config_hash": (cfg_path.read_bytes() if cfg_path.exists() else b"") .hex()}, indent=2)
    )

    cents, ids = Router(root).load_centroids()
    if len(ids) >= 2:
        dH, iters, resid, ehash = composite_settle(cents, list(range(min(4, len(ids)))))
        print(f"[smoke] composite: dH={dH:.4f} iters={iters} resid={resid:.2e} ehash={ehash[:8]}..")
    else:
        print("[smoke] composite skipped (insufficient centroids)")
    print(f"[smoke] OK: {len(recs)} lattices")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
