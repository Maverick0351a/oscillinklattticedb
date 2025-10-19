"""Metadata helpers for lattice display names.
SPDX-License-Identifier: BUSL-1.1
"""
from __future__ import annotations

import json
from pathlib import Path
from latticedb.utils import atomic_write_text


def names_path(root: Path) -> Path:
    return root / "metadata" / "names.json"


def load_names(root: Path) -> dict[str, str]:
    p = names_path(root)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_names(root: Path, names: dict[str, str]) -> None:
    (root / "metadata").mkdir(parents=True, exist_ok=True)
    atomic_write_text(names_path(root), json.dumps(names, ensure_ascii=False, indent=2))
