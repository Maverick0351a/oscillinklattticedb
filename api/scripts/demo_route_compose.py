import argparse
import json
import sys

import requests

p = argparse.ArgumentParser()
p.add_argument("--url", default="http://127.0.0.1:8080")
p.add_argument("--q", default="What is Oscillink?")
args = p.parse_args()

url = args.url.rstrip("/")

r1 = requests.post(f"{url}/v1/latticedb/route", json={"q": args.q, "k_lattices": 8}, timeout=10)
print("ROUTE", r1.status_code)
try:
    jr = r1.json()
except Exception:
    print(r1.text)
    sys.exit(1)
cands = jr.get("candidates", [])
sel = [c.get("lattice_id") for c in cands[:3] if c.get("lattice_id")]

r2 = requests.post(f"{url}/v1/latticedb/compose", json={"q": args.q, "lattice_ids": sel}, timeout=15)
print("COMPOSE", r2.status_code)
try:
    jc = r2.json()
except Exception:
    print(r2.text)
    sys.exit(1)

print(json.dumps({"route": cands, "compose": jc}, indent=2))

# Verify composite vs DB root if present
comp = (jc or {}).get("context_pack", {}).get("receipts", {}).get("composite")
ok = None
if comp and isinstance(comp, dict) and comp.get("db_root"):
    rdb = requests.get(f"{url}/v1/db/receipt", timeout=5)
    if rdb.ok:
        dbj = rdb.json()
        ok = (dbj.get("db_root") == comp.get("db_root"))
print(json.dumps({"db_root_match": ok}, indent=2))
