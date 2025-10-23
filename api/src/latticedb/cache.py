from __future__ import annotations
import time
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import pandas as pd

try:
    import pyarrow.parquet as pq  # type: ignore
    _HAS_PA = True
except Exception:  # pragma: no cover - optional optimization
    _HAS_PA = False


@dataclass(frozen=True)
class _FileSig:
    path: str
    mtime_ns: int
    size: int


def _sig(p: Path) -> Optional[_FileSig]:
    try:
        if not p.exists():
            return None
        s = p.stat()
        mtns = getattr(s, "st_mtime_ns", int(s.st_mtime * 1e9))
        return _FileSig(str(p), int(mtns), int(s.st_size))
    except Exception:  # pragma: no cover - filesystem race/permission
        return None


def _sig_tuple(paths: Tuple[Path, ...]) -> Tuple[Optional[_FileSig], ...]:
    return tuple(_sig(p) for p in paths)


class ManifestCache:
    """TTL cache for manifest.parquet with invalidation when signatures change."""

    def __init__(self, ttl_seconds: int = 60):
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._df: Optional[pd.DataFrame] = None
        self._sig: Optional[Tuple[Optional[_FileSig], ...]] = None
        self._expires_at: float = 0.0

    def get(self, root: Path) -> pd.DataFrame:
        root = root.resolve()
        manifest = root / "manifest.parquet"
        db_receipt = root / "receipts" / "db_receipt.json"
        config = root / "receipts" / "config.json"
        sig = _sig_tuple((manifest, db_receipt, config))
        now = time.time()

        with self._lock:
            if self._df is not None and now < self._expires_at and sig == self._sig:
                return self._df

        # Load outside the lock
        if manifest.exists():
            if _HAS_PA:
                df = pq.read_table(str(manifest)).to_pandas()
            else:
                df = pd.read_parquet(str(manifest))
        else:
            df = pd.DataFrame()

        with self._lock:
            self._df = df
            self._sig = sig
            self._expires_at = now + self._ttl
            return self._df

    def clear(self) -> None:
        """Clear cached manifest and expire immediately."""
        with self._lock:
            self._df = None
            self._sig = None
            self._expires_at = 0.0


manifest_cache = ManifestCache()


class MMapLRU:
    """Tiny LRU for np.load(..., mmap_mode='r'), keyed by file signature."""

    def __init__(self, cap: int = 8):
        from collections import OrderedDict

        self._cap = int(max(1, cap))
        self._lock = threading.Lock()
        self._store: "OrderedDict[_FileSig, np.ndarray]" = OrderedDict()
        self._OrderedDict = OrderedDict
        # Simple circuit breaker for platforms where mmap flakes
        self._fail_count = 0
        self._fail_limit = 3

    def get(self, path: Path) -> Optional[np.ndarray]:
        if self._fail_count >= self._fail_limit:
            return None
        sig = _sig(path)
        if sig is None:
            return None
        with self._lock:
            arr = self._store.pop(sig, None)
            if arr is not None:
                self._store[sig] = arr  # MRU
                return arr
        try:
            arr = np.load(str(path), mmap_mode="r")  # read-only
        except Exception:
            with self._lock:
                self._fail_count += 1
            return None
        with self._lock:
            self._fail_count = 0
            self._store[sig] = arr
            while len(self._store) > self._cap:
                try:
                    self._store.popitem(last=False)  # LRU
                except Exception:
                    break
        return arr

    def clear(self) -> None:
        """Clear all cached arrays, releasing any memory-mapped file handles."""
        with self._lock:
            try:
                self._store.clear()
            except Exception:
                self._store = self._OrderedDict()


mmap_arrays = MMapLRU()
