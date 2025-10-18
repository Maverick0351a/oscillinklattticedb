from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict
from datetime import datetime, timezone


@dataclass
class CompactionReceipt:
    version: str
    reclaimed_files: int
    reclaimed_bytes: int
    kept_hashes: int
    ts: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)


def compact(db_root: Path) -> CompactionReceipt:
    receipts_root = db_root/"receipts"
    dedup_map = receipts_root/"dedup_map.jsonl"
    if not dedup_map.exists():
        return CompactionReceipt(version="1", reclaimed_files=0, reclaimed_bytes=0, kept_hashes=0, ts=datetime.now(timezone.utc).isoformat())
    hashes: Dict[str, str] = {}
    with dedup_map.open("r", encoding="utf-8") as f:
        for ln in f:
            try:
                obj = json.loads(ln)
            except Exception:
                continue
            h = obj.get("file_sha256")
            lat = obj.get("lattice_id")
            if isinstance(h, str) and isinstance(lat, str):
                hashes[h] = lat
    # Best-effort: delete empty group dirs whose receipt.json is missing
    reclaimed_files = 0
    reclaimed_bytes = 0
    groups = (db_root/"groups")
    if groups.exists():
        for g in groups.glob("G-*/L-*"):
            receipt = g/"receipt.json"
            if not receipt.exists():
                # Remove stray dir
                try:
                    for p in g.glob("**/*"):
                        if p.is_file():
                            reclaimed_files += 1
                            try:
                                reclaimed_bytes += p.stat().st_size
                            except Exception:
                                pass
                    import shutil
                    shutil.rmtree(g, ignore_errors=True)
                except Exception:
                    pass
    rec = CompactionReceipt(
        version="1",
        reclaimed_files=reclaimed_files,
        reclaimed_bytes=reclaimed_bytes,
        kept_hashes=len(hashes),
        ts=datetime.now(timezone.utc).isoformat(),
    )
    (receipts_root/"compaction.receipt.json").write_text(rec.to_json(), encoding="utf-8")
    return rec


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", dest="db", type=str, default="latticedb")
    args = ap.parse_args()
    r = compact(Path(args.db))
    print(r.to_json())
