import argparse
from pathlib import Path
import json

import yaml


def read_text_from_pdf(path: Path) -> str:
    try:
        import importlib
        mod = importlib.import_module("pdfminer.high_level")
        return getattr(mod, "extract_text")(str(path)) or ""
    except Exception as e:
        return f"[pdf extract error: {e}]"


def read_text_from_docx(path: Path) -> str:
    try:
        import importlib
        docx = importlib.import_module("docx")
        Document = getattr(docx, "Document")
        doc = Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs)
    except Exception as e:
        return f"[docx extract error: {e}]"


def read_text_from_csv(path: Path, max_rows: int = 50) -> str:
    try:
        import csv
        out = []
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            reader = csv.reader(f)
            for i, row in enumerate(reader):
                out.append(", ".join(row))
                if i >= max_rows:
                    break
        return "\n".join(out)
    except Exception as e:
        return f"[csv read error: {e}]"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="bench/assets/manifest.yml")
    ap.add_argument("--out-dir", default="sample_data/assets_txt")
    args = ap.parse_args()

    man_path = Path(args.manifest)
    if not man_path.exists():
        raise SystemExit(f"manifest not found: {man_path}")
    data = yaml.safe_load(man_path.read_text()) or {}
    base_dir = Path(data.get("base_dir", "bench/assets"))
    files = data.get("files", [])

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    total_bytes = 0
    for item in files:
        rel = Path(item.get("path"))
        src = (base_dir / rel).resolve()
        if not src.exists():
            continue
        ext = src.suffix.lower()
        if ext == ".pdf":
            text = read_text_from_pdf(src)
        elif ext == ".docx":
            text = read_text_from_docx(src)
        elif ext == ".csv":
            text = read_text_from_csv(src)
        else:
            # skip unknown types
            continue
        stem = rel.with_suffix("").as_posix().replace("/", "_").replace("\\", "_")
        dst = out_dir / f"{stem}.txt"
        dst.write_text(text, encoding="utf-8", errors="ignore")
        written += 1
        total_bytes += dst.stat().st_size

    print(json.dumps({"written": written, "out_dir": str(out_dir), "bytes": total_bytes}, indent=2))


if __name__ == "__main__":
    main()
