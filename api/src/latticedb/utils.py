import hashlib
import json
import os
import random
import warnings
from typing import Any, Iterable, List, Dict
from pathlib import Path
import tempfile
import io

RANDOM_SEED = int(os.environ.get("LATTICEDB_SEED","1337"))

def stable_hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",",":"))

def state_sig(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()

def set_determinism(seed: int | None = None) -> None:
    """Best-effort determinism: seeds RNGs and limits threads if possible.

    This is safe to call multiple times.
    """
    s = int(seed if seed is not None else RANDOM_SEED)
    random.seed(s)
    os.environ.setdefault("PYTHONHASHSEED", str(s))
    # NumPy
    try:
        import numpy as _np  # type: ignore
        _np.random.seed(s)
    except Exception:
        pass
    # Torch (optional)
    try:
        import torch as _torch  # type: ignore
        _torch.manual_seed(s)
        if _torch.cuda.is_available():
            _torch.cuda.manual_seed_all(s)
        try:
            _torch.use_deterministic_algorithms(True, warn_only=True)  # type: ignore[attr-defined]
        except Exception:
            pass
    except Exception:
        pass
    # Threading caps (won't override if user set)
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")


def apply_determinism_if_enabled() -> bool:
    """Enable determinism when OSC_DETERMINISTIC or LATTICEDB_DETERMINISTIC is truthy.

    Returns True if determinism was enabled.
    """
    flag = str(os.environ.get("OSC_DETERMINISTIC") or os.environ.get("LATTICEDB_DETERMINISTIC") or "").lower()
    if flag in ("1", "true", "yes", "on"):  # enable
        try:
            set_determinism()
            return True
        except Exception as e:  # pragma: no cover - best-effort
            warnings.warn(f"determinism request failed: {e}")
            return False
    return False


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
        tmp.write(data)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    atomic_write_bytes(path, text.encode(encoding))


def append_jsonl(path: Path, obj: Any, encoding: str = "utf-8") -> None:
    """Append a single JSON line to a file, creating parents if needed.

    This is a simple append (WAL-like); callers should keep records small.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding=encoding, newline="\n") as f:
        f.write(json.dumps(obj) + "\n")


class Manifest:
    """Simple manifest over groups/lattices; minimal API for router and receipts.

    Stored as a Parquet file for simplicity; can be swapped for sqlite later.
    """

    def __init__(self, root: Path):
        self.root = root
        self.path = root / "manifest.parquet"

    def append(self, entries: Iterable[dict[str, Any]]) -> None:
        import pandas as pd
        df_new = pd.DataFrame(list(entries))
        if self.path.exists():
            df_old = pd.read_parquet(self.path)
            df = pd.concat([df_old, df_new], ignore_index=True)
        else:
            df = df_new
        buf = io.BytesIO()
        df.to_parquet(buf, index=False)
        atomic_write_bytes(self.path, buf.getvalue())

    def list_lattices(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        import pandas as pd
        df = pd.read_parquet(self.path)
        recs_any = df.to_dict(orient="records")
        # Ensure keys are strings for type checker and consistency
        recs: List[Dict[str, Any]] = [ {str(k): v for k, v in r.items()} for r in recs_any ]
        return recs