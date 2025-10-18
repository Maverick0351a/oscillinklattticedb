from __future__ import annotations

from latticedb.ingest import ingest_dir  # type: ignore[import]


def test_ingest_empty_directory(tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    out_dir = tmp_path / "out"

    receipts = ingest_dir(input_dir, out_dir)

    assert receipts == []
    assert not (out_dir / "groups").exists()
    assert not (out_dir / "router" / "centroids.f32").exists()
    assert (out_dir / "receipts").exists()
