from starlette.testclient import TestClient


def test_manifest_search_empty_and_paging(monkeypatch, tmp_path):
    import app.main as m
    from latticedb.utils import Manifest

    # Stub Manifest.list_lattices to a small set
    class _StubMan(Manifest):
        def __init__(self, root):
            pass

        def list_lattices(self):
            return [
                {"group_id": "G-1", "lattice_id": "L-1", "source_file": "a.txt", "deltaH_total": 1.0, "created_at": "2024-01-01T00:00:00Z"},
                {"group_id": "G-2", "lattice_id": "L-2", "source_file": "b.txt", "deltaH_total": 2.0, "created_at": "2024-01-02T00:00:00Z"},
            ]

    import app.routers.manifest as man
    monkeypatch.setattr(man, "Manifest", _StubMan, raising=False)

    client = TestClient(m.app)
    r = client.get("/v1/latticedb/search", params={"q": "", "limit": 1, "offset": 1})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2 and len(body["items"]) == 1


def test_set_lattice_metadata_validates(monkeypatch, tmp_path):
    import app.main as m
    from latticedb.utils import Manifest

    class _StubMan(Manifest):
        def __init__(self, root):
            pass

        def list_lattices(self):
            return [{"lattice_id": "L-1"}]

    import app.routers.manifest as man
    monkeypatch.setattr(man, "Manifest", _StubMan, raising=False)

    client = TestClient(m.app)
    # Missing lattice
    r1 = client.put("/v1/latticedb/lattice/L-404/metadata", json={"db_path": str(tmp_path), "display_name": "X"})
    assert r1.status_code == 404
    # Empty name
    r2 = client.put("/v1/latticedb/lattice/L-1/metadata", json={"db_path": str(tmp_path), "display_name": "  "})
    assert r2.status_code == 400
    # Too long
    r3 = client.put("/v1/latticedb/lattice/L-1/metadata", json={"db_path": str(tmp_path), "display_name": "x" * 300})
    assert r3.status_code == 400
