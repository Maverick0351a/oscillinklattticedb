import numpy as np
from pathlib import Path
from typing import Dict, List, Tuple, Optional

try:  # optional import to avoid hard coupling at import time
    from app.core.config import settings  # type: ignore
    from .cache import mmap_arrays  # type: ignore
except Exception:  # pragma: no cover - fallback if app context not available
    settings = None
    mmap_arrays = None

class Router:
    def __init__(self, root: Path):
        self.root = root
        self.centroids_path = root/"router/centroids.f32"
        self.centroids_npy = root/"router/centroids.npy"
        self.meta_path = root/"router/meta.parquet"

    def load_centroids(self) -> Tuple[np.ndarray, List[str]]:
        # Prefer .npy if present (explicit shape), else fall back to raw f32
        if self.centroids_npy.exists():
            try:
                if settings is not None and getattr(settings, "mmap_enabled", False) and mmap_arrays is not None:
                    arr = mmap_arrays.get(self.centroids_npy)
                    if arr is not None:
                        cents = arr
                    else:
                        cents = np.load(self.centroids_npy, mmap_mode="r")
                else:
                    cents = np.load(self.centroids_npy, mmap_mode="r")
                if cents.ndim != 2:
                    cents = cents.reshape(-1, cents.shape[-1])
                ids: List[str] = []
                if self.meta_path.exists():
                    import pandas as pd
                    df = pd.read_parquet(self.meta_path)
                    ids = df["lattice_id"].tolist()
                else:
                    ids = [f"L-{i+1:06d}" for i in range(cents.shape[0])]
                return cents.astype(np.float32, copy=False), ids
            except Exception:
                # Fallback to raw f32 path
                pass

        if not self.centroids_path.exists():
            return np.zeros((0,32), dtype=np.float32), []
        arr = np.fromfile(self.centroids_path, dtype=np.float32)
        if arr.size == 0:
            return np.zeros((0,32), dtype=np.float32), []
        # Determine embedding dim from config.json if present
        D = 32
        cfg = self.root/"receipts"/"config.json"
        if cfg.exists():
            import json
            try:
                cfgj = json.loads(cfg.read_text())
                D = int(cfgj.get("embed_dim", D))
                if D <= 0:
                    D = 32
            except Exception:
                D = 32
        N = arr.size // D
        cents = arr.reshape(N, D)
        ids = []
        if self.meta_path.exists():
            import pandas as pd
            df = pd.read_parquet(self.meta_path)
            ids = df["lattice_id"].tolist()
        else:
            ids = [f"L-{i+1:06d}" for i in range(N)]
        return cents, ids

    def route(self, q_vec: np.ndarray, k: int = 8, filters: Optional[Dict[str,str]] = None):
        cents, ids = self.load_centroids()
        if cents.shape[0] == 0:
            return []
        v = q_vec / (np.linalg.norm(q_vec)+1e-9)
        C = cents / (np.linalg.norm(cents, axis=1, keepdims=True)+1e-9)
        sims = C @ v
        order = np.argsort(-sims)[:k]
        return [(ids[i], float(sims[i])) for i in order]