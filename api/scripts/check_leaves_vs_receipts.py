from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db-path", default="latticedb")
    args = ap.parse_args()

    root = Path(args.db_path)
    db_receipt_path = root / "receipts" / "db_receipt.json"
    if not db_receipt_path.exists():
        print("db_receipt.json not found at:", db_receipt_path)
        return 1
    db = json.loads(db_receipt_path.read_text(encoding="utf-8"))
    leaves: List[str] = list(db.get("leaves", []))

    rec_sigs: List[str] = []
    for p in (root / "groups").rglob("receipt.json"):
        try:
            rj = json.loads(p.read_text(encoding="utf-8"))
            sig = rj.get("state_sig")
            if isinstance(sig, str) and sig:
                rec_sigs.append(sig)
        except Exception:
            pass

    missing = [x for x in leaves if x not in rec_sigs]

    print("DB leaves:", len(leaves))
    print("Provided lattice receipts:", len(rec_sigs))
    print("Missing count:", len(missing))
    if missing:
        print("Missing (first 10):", missing[:10])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
