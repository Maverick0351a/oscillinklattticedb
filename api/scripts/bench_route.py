import argparse
import json
import statistics
import time
from pathlib import Path

import requests

p = argparse.ArgumentParser()
p.add_argument("--url", default="http://127.0.0.1:8080")
p.add_argument("--runs", type=int, default=50)
p.add_argument("--q", default="What is Oscillink?")
args = p.parse_args()

lat = []
for _ in range(args.runs):
    t0 = time.perf_counter()
    _ = requests.post(f"{args.url}/v1/latticedb/route", json={"q": args.q})
    t1 = time.perf_counter()
    lat.append((t1 - t0) * 1000)

summary = {
    "runs": args.runs,
    "p50_ms": statistics.median(lat) if lat else None,
    "p95_ms": (sorted(lat)[int(0.95 * len(lat)) - 1] if lat else None),
}
Path("bench").mkdir(exist_ok=True, parents=True)
Path("bench/route_summary.json").write_text(json.dumps(summary, indent=2))
print(json.dumps(summary, indent=2))
