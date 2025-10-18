from __future__ import annotations

import argparse
import json
from pathlib import Path

from latticedb.watcher import single_scan as watcher_single_scan


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", type=str, required=True, help="DB root output dir")
    ap.add_argument("--firm", type=str, default=None, help="Path to firm.yaml (optional)")
    ap.add_argument("--embed-model", default="bge-small-en-v1.5")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--strict-hash", type=int, default=0)
    args = ap.parse_args()

    res = watcher_single_scan(
        input_root=Path(args.input).resolve(),
        db_root=Path(args.out).resolve(),
        firm_path=Path(args.firm).resolve() if args.firm else None,
        embed_model=args.embed_model,
        embed_device=args.device,
        embed_batch_size=int(args.batch_size),
        embed_strict_hash=bool(args.strict_hash),
    )
    print(json.dumps(res, indent=2))
