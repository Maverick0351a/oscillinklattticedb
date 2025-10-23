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

    # Prefer to use the exact leaf set recorded in the db_receipt when available.
    leaves_db = db.get("leaves")
    cfg_hash = db.get("config_hash", "")
    provided_sigs = []
    for v in lattice_receipts.values():
        try:
            sig = str(v.get("state_sig", ""))
            if sig:
                provided_sigs.append(sig)
        except Exception:
            continue

    if isinstance(leaves_db, list) and len(leaves_db) > 0:
        required = [x for x in leaves_db if x != cfg_hash]
        missing = [x for x in required if x not in provided_sigs]
        if missing:
            return {"verified": False, "reason": "missing_receipts", "missing": missing}
        # Compute root over recorded leaves to avoid ordering differences
        root_actual = merkle_root(leaves_db)
    else:
        # Fallback: compute root over all provided receipts plus config hash
        leaves = provided_sigs + [cfg_hash]
        root_actual = merkle_root(leaves)
    if root_actual != root_expected:
        return {"verified": False, "reason": "db_root mismatch"}
    return {"verified": True, "reason": "ok"}