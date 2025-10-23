import argparse
import json
import os
import platform
import time
from pathlib import Path

try:
    import psutil  # type: ignore
except Exception:  # pragma: no cover - fallback if psutil not installed
    psutil = None


def get_rss_mb() -> float | None:
    if psutil is None:
        return None
    process = psutil.Process(os.getpid())
    rss = process.memory_info().rss
    return rss / (1024 * 1024)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="_bench/memory_rss.json")
    p.add_argument("--sleep", type=float, default=0.5, help="optional dwell to stabilize measurement")
    p.add_argument("--label", default=None, help="optional label to include in the output (e.g., baseline, warmed)")
    args = p.parse_args()

    # Optional lightweight workload placeholder (noop)
    time.sleep(args.sleep)

    payload = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "rss_mb": get_rss_mb(),
        "note": "If rss_mb is null, install psutil in dev extras to enable measurement.",
    }
    if args.label:
        payload["label"] = str(args.label)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(payload, indent=2))
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
