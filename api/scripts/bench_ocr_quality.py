import argparse
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--labels-csv", required=True, help="CSV with columns: file, ocr_label")
    p.add_argument("--out", default="_bench/bench_ocr_quality.json")
    args = p.parse_args()

    # This scaffold does not include an OCR pipeline; this is a stub that records intent.
    payload = {
        "note": "OCR governance is not implemented in this scaffold. Provide your OCR pipeline and labels to compute metrics.",
        "labels_csv": args.labels_csv,
        "metrics": {
            "low_ocr_rate": None,
            "abstain_low_ocr": None,
            "penalty_engaged_pct": None,
        },
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(payload, indent=2))
    print(json.dumps({"written": args.out}, indent=2))


if __name__ == "__main__":
    main()
