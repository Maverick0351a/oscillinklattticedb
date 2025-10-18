from __future__ import annotations

import json
import numpy as np
from pathlib import Path

from latticedb.router import Router


def test_load_centroids_infers_dim_and_fallback_ids(tmp_path: Path):
    db = tmp_path / "db"
    (db / "router").mkdir(parents=True)
    # Write two 4-dim centroids without meta
    cents = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], dtype=np.float32)
    (db / "router" / "centroids.f32").write_bytes(cents.tobytes())
    # Write config to specify dim=4
    (db / "receipts").mkdir(parents=True)
    (db / "receipts" / "config.json").write_text(json.dumps({"embed_dim": 4}))

    C, ids = Router(db).load_centroids()
    assert C.shape == (2, 4)
    # Fallback ids when meta is missing
    assert ids == ["L-000001", "L-000002"]


def test_route_orders_by_cosine_similarity(tmp_path: Path):
    db = tmp_path / "db"
    (db / "router").mkdir(parents=True)
    (db / "receipts").mkdir(parents=True)
    # 2-D points and a query closer to the second
    cents = np.array([[1, 0], [0, 1], [1, 1]], dtype=np.float32)
    (db / "router" / "centroids.f32").write_bytes(cents.tobytes())
    (db / "receipts" / "config.json").write_text(json.dumps({"embed_dim": 2}))
    q = np.array([0.0, 1.0], dtype=np.float32)
    res = Router(db).route(q, k=2)
    assert len(res) == 2
    # First should be the [0,1] centroid
    assert res[0][0] == "L-000002"