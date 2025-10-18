import hashlib
import json
from pathlib import Path
from typing import Dict, Any
from .merkle import merkle_root

def verify_composite(db_receipt_path: Path, composite: Dict[str,Any], lattice_receipts: Dict[str,Dict[str,Any]]) -> Dict[str,Any]:
    if not db_receipt_path.exists():
        return {"verified": False, "reason": "db_receipt missing"}
    db = json.loads(db_receipt_path.read_text())
    root_expected = db.get("db_root","")

    comp = dict(composite)
    sig_given = comp.get("state_sig","")
    comp.pop("state_sig", None)
    norm = json.dumps(comp, sort_keys=True, separators=(",",":")).encode("utf-8")
    sig_actual = hashlib.sha256(norm).hexdigest()
    if sig_given != sig_actual:
        return {"verified": False, "reason": "composite state_sig mismatch"}

    leaves = [ lattice_receipts[lid]["state_sig"] for lid in composite.get("lattice_ids",[]) if lid in lattice_receipts ]
    leaves.append(db.get("config_hash",""))
    root_actual = merkle_root(leaves)
    if root_actual != root_expected:
        return {"verified": False, "reason": "db_root mismatch"}
    return {"verified": True, "reason": "ok"}