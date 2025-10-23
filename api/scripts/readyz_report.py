import argparse
import json
import sys
from urllib.parse import urljoin

import requests


def main():
    p = argparse.ArgumentParser(description="Call /readyz and exit nonzero if not ready")
    p.add_argument("--url", default="http://127.0.0.1:8080", help="Base URL of API (no trailing slash)")
    p.add_argument("--db-path", dest="db_path", default=None, help="Optional absolute DB path to pass to /readyz")
    p.add_argument("--strict", action="store_true", help="Enable strict readiness mode")
    p.add_argument("--summary", action="store_true", help="Enable summary readiness mode (cheap checks)")
    p.add_argument("--schema-limit", type=int, default=None, help="Optional schema validation limit")
    p.add_argument("--timeout", type=float, default=5.0, help="HTTP timeout seconds")
    args = p.parse_args()

    endpoint = urljoin(args.url.rstrip("/") + "/", "readyz")
    params = {}
    if args.db_path:
        params["db_path"] = args.db_path
    if args.strict:
        params["strict"] = "true"
    if args.summary:
        params["summary"] = "true"
    if args.schema_limit is not None:
        params["schema_limit"] = str(int(args.schema_limit))

    try:
        r = requests.get(endpoint, params=params, timeout=args.timeout)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(json.dumps({"ok": False, "error": f"request_failed: {e}"}, indent=2))
        sys.exit(2)

    ready = bool(data.get("ready"))
    # Pretty print a compact report to help CI logs
    report = {
        "url": endpoint,
        "params": params,
        "ready": ready,
        "warnings": data.get("warnings", []),
        "failed_checks": [k for k, v in (data.get("checks") or {}).items() if not v],
    }
    print(json.dumps(report, indent=2))
    sys.exit(0 if ready else 1)


if __name__ == "__main__":
    main()
