import hashlib
from pathlib import Path
from typing import Optional

import pooch
import yaml


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    manifest_path = Path("bench/assets/manifest.yml")
    if not manifest_path.exists():
        raise SystemExit(f"manifest not found: {manifest_path}")
    data = yaml.safe_load(manifest_path.read_text()) or {}
    base_dir = Path(data.get("base_dir", "bench/assets")).resolve()
    files = data.get("files", [])
    base_dir.mkdir(parents=True, exist_ok=True)

    computed = []
    for item in files:
        url: str = item["url"]
        expect: Optional[str] = item.get("sha256")
        rel = Path(item["path"])  # e.g., pdfs/file.pdf
        target = base_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)

        known_hash = None
        if expect:
            known_hash = f"sha256:{expect}"
        try:
            fname = pooch.retrieve(url=url, known_hash=known_hash)
        except Exception as e:
            print(f"error: failed to fetch {url}: {e}")
            continue
        # Move into target location if different
        src = Path(fname)
        if src.resolve() != target.resolve():
            if target.exists():
                target.unlink()
            src.replace(target)

        size = target.stat().st_size
        if not expect:
            got = sha256_of(target)
            computed.append({"path": str(rel), "sha256": got, "size": size})
            print(f"ok: {rel} ({size} bytes) sha256={got}")
        else:
            print(f"ok: {rel} ({size} bytes) verified")

    if computed:
        print("\nHashes to pin in bench/assets/manifest.yml:")
        for c in computed:
            print(f"- path: {c['path']}  sha256: {c['sha256']}  size: {c['size']}")


if __name__ == "__main__":
    main()
