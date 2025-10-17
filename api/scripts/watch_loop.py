from __future__ import annotations

import argparse
from pathlib import Path

from latticedb.watcher import watch_loop


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--firm", default=None)
    ap.add_argument("--interval", type=int, default=30)
    ap.add_argument("--embed-model", default="bge-small-en-v1.5")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--strict-hash", type=int, default=0)
    args = ap.parse_args()

    watch_loop(
        input_root=Path(args.input).resolve(),
        db_root=Path(args.out).resolve(),
        interval_secs=int(args.interval),
        embed_model=args.embed_model,
        embed_device=args.device,
        embed_batch_size=int(args.batch_size),
        embed_strict_hash=bool(args.strict_hash),
        firm_path=Path(args.firm).resolve() if args.firm else None,
    )
