import pytest


def test_version_fallback_to_dev(monkeypatch):
    import app.routers.ops as ops
    import app.main as m

    monkeypatch.setattr(m, "pkg_version", lambda *_: (_ for _ in ()).throw(m.PackageNotFoundError()), raising=True)
    res = ops.version()
    assert res["version"] == "0.0.0+dev"
    assert "git_sha" in res


def test_get_db_receipt_errors(tmp_path):
    import app.routers.ops as ops
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as ei:
        ops.get_db_receipt(db_path=str(tmp_path))
    assert ei.value.status_code == 404

    p = tmp_path / "receipts"
    p.mkdir(parents=True)
    f = p / "db_receipt.json"
    f.write_text("not json")
    with pytest.raises(HTTPException) as ei2:
        ops.get_db_receipt(db_path=str(tmp_path))
    assert ei2.value.status_code == 500


def test_readyz_smoke(tmp_path):
    import app.routers.ops as ops
    res = ops.readyz(db_path=str(tmp_path))
    assert res["ready"] is False
    assert isinstance(res.get("checks"), dict)
