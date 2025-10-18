from __future__ import annotations

from pathlib import Path

from latticedb.shards import write_shards_yaml, apply_backend_promotions


def _touch(p: Path, size: int = 0):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * size)


def test_write_shards_yaml_and_preserve(tmp_path: Path):
    root = tmp_path / "assets"
    (root / "a").mkdir(parents=True)
    (root / "b").mkdir(parents=True)
    _touch(root / "a" / "f1.txt", 3)
    _touch(root / "b" / "f2.txt", 5)
    _touch(root / "at_root.txt", 2)

    shards_path = tmp_path / "shards.yaml"
    st = write_shards_yaml(root, shards_path)
    ids = {s.id for s in st.shards}
    assert {"shard-a", "shard-b", "shard-root"}.issubset(ids)
    # Flip one backend and rewrite to ensure preservation
    st.shards[0].active_backend = "faiss"
    shards_path.write_text("""version: '1'\nbase_dir: .\nshards:\n- {id: %s, path: a, size_bytes: 3, file_count: 1, active_backend: faiss}\n- {id: shard-b, path: b, size_bytes: 5, file_count: 1, active_backend: jsonl}\n- {id: shard-root, path: ., size_bytes: 2, file_count: 1, active_backend: jsonl}\n""" % st.shards[0].id)
    st2 = write_shards_yaml(root, shards_path)
    m = {s.id: s for s in st2.shards}
    assert m[st.shards[0].id].active_backend == "faiss"


def test_apply_backend_promotions(tmp_path: Path):
    root = tmp_path / "assets"
    (root / "x").mkdir(parents=True)
    (root / "y").mkdir(parents=True)
    _touch(root / "x" / "f1.txt", 1)
    _touch(root / "y" / "f2.txt", 1)
    shards_path = tmp_path / "shards.yaml"
    st = write_shards_yaml(root, shards_path)
    # Promote one shard
    updated = apply_backend_promotions(shards_path, {st.shards[0].id: "faiss"})
    m = {s.id: s for s in updated.shards}
    assert m[st.shards[0].id].active_backend == "faiss"
