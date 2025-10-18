import argparse
import json

import requests

p = argparse.ArgumentParser()
p.add_argument("--db", default="latticedb")
p.add_argument("--q", required=True)
p.add_argument("--url", default="http://127.0.0.1:8080")
args = p.parse_args()

r1 = requests.post(f"{args.url}/v1/latticedb/route", json={"db_path": args.db, "q": args.q, "k_lattices": 8})
cands = r1.json().get("candidates",[])
sel = [c["lattice_id"] for c in cands[:3]]
r2 = requests.post(f"{args.url}/v1/latticedb/compose", json={"db_path": args.db, "q": args.q, "lattice_ids": sel})
print(json.dumps({"route": cands, "compose": r2.json()}, indent=2))