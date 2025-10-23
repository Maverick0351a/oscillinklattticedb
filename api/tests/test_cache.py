from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd

from latticedb.cache import ManifestCache, MMapLRU


def _write_manifest(path: Path, rows: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(
        {
            "lattice_id": [str(i) for i in range(rows)],
            "shard_id": [0 for _ in range(rows)],
        }
    )
    df.to_parquet(path)


def test_manifest_cache_invalidation_by_signature(tmp_path: Path) -> None:
    # layout: root/{manifest.parquet, receipts/db_receipt.json, receipts/config.json}
    root = tmp_path
    receipts = root / "receipts"
    receipts.mkdir(parents=True, exist_ok=True)
    (receipts / "db_receipt.json").write_text("{}", encoding="utf-8")
    (receipts / "config.json").write_text("{}", encoding="utf-8")

    manifest = root / "manifest.parquet"
    cache = ManifestCache(ttl_seconds=60)

    # initial write: 1 row
    _write_manifest(manifest, rows=1)
    df1 = cache.get(root)
    assert len(df1) == 1

    # update manifest immediately: 2 rows -> signature change should bypass TTL
    _write_manifest(manifest, rows=2)
    df2 = cache.get(root)
    assert len(df2) == 2


def test_manifest_cache_ttl_retains_when_unchanged(tmp_path: Path) -> None:
    root = tmp_path
    (root / "receipts").mkdir(parents=True, exist_ok=True)
    (root / "receipts" / "db_receipt.json").write_text("{}", encoding="utf-8")
    (root / "receipts" / "config.json").write_text("{}", encoding="utf-8")
    manifest = root / "manifest.parquet"

    _write_manifest(manifest, rows=3)
    cache = ManifestCache(ttl_seconds=1)
    first = cache.get(root)
    second = cache.get(root)
    # Within TTL and unchanged signature, should be the same object instance
    assert first is second

    # After TTL expires but unchanged, a new object can be returned but content matches
    time.sleep(1.1)
    third = cache.get(root)
    assert len(third) == 3


def test_mmap_lru_basic_and_eviction(tmp_path: Path) -> None:
    # prepare two npy files
    p1 = tmp_path / "a.npy"
    p2 = tmp_path / "b.npy"
    np.save(p1, np.arange(10, dtype=np.float32))
    np.save(p2, np.arange(5, dtype=np.int16))

    lru = MMapLRU(cap=1)

    a1 = lru.get(p1)
    assert a1 is not None
    assert a1.shape == (10,)
    assert a1.dtype == np.float32
    assert getattr(a1, "flags", None) is not None and a1.flags.writeable is False

    # MRU hit returns same object
    a2 = lru.get(p1)
    assert a2 is a1

    # Load second -> evicts first (cap=1)
    b1 = lru.get(p2)
    assert b1 is not None and b1.shape == (5,)

    # Re-get first -> should not be same object as a1 (was evicted and reloaded)
    a3 = lru.get(p1)
    assert a3 is not None
    assert a3.shape == (10,)
    assert a3 is not a1


def test_mmap_lru_signature_change_reload(tmp_path: Path) -> None:
    p = tmp_path / "c.npy"
    np.save(p, np.zeros((4,), dtype=np.uint8))

    lru = MMapLRU(cap=2)
    arr1 = lru.get(p)
    assert arr1 is not None
    # Release any OS handles held by the LRU on Windows before overwriting
    lru.clear()
    del arr1
    import gc
    gc.collect()
    # overwrite with different size and content -> signature changes
    np.save(p, np.ones((8,), dtype=np.uint8))
    arr2 = lru.get(p)
    assert arr2 is not None
    assert arr2.shape == (8,)
