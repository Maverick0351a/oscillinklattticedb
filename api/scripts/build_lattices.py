import argparse
import hashlib
import json
from pathlib import Path
from latticedb.ingest import ingest_dir
from latticedb.merkle import merkle_root

p = argparse.ArgumentParser()
p.add_argument("--input", required=True)
p.add_argument("--out", required=True)
p.add_argument("--embed-model", default="bge-small-en-v1.5")
p.add_argument("--device", default="cpu", choices=["cpu","cuda"]) 
p.add_argument("--batch-size", type=int, default=32)
p.add_argument("--strict-hash", type=int, default=0)
args = p.parse_args()

out_dir = Path(args.out)
receipts = ingest_dir(
	Path(args.input),
	out_dir,
	embed_model=args.embed_model,
	embed_device=args.device,
	embed_batch_size=int(args.batch_size),
	embed_strict_hash=bool(args.strict_hash),
)
leaves = [r.state_sig for r in receipts]
# Compute config hash from receipts/config.json if present; fallback to stub
cfg_path = out_dir/"receipts"/"config.json"
if cfg_path.exists():
	config_hash = hashlib.sha256(cfg_path.read_bytes()).hexdigest()
else:
	config_hash = hashlib.sha256(b"stub-config").hexdigest()
root = merkle_root(leaves + [config_hash])
(out_dir/"receipts").mkdir(parents=True, exist_ok=True)
(out_dir/"receipts/db_receipt.json").write_text(json.dumps({"version":"1","db_root":root,"config_hash":config_hash, "leaves": leaves + [config_hash]}, indent=2))
print(json.dumps({"count": len(receipts), "db_root": root}, indent=2))