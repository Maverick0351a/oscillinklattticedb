from fastapi.testclient import TestClient
from app.main import app

def test_models_endpoint_lists_presets():
    client = TestClient(app)
    r = client.get("/v1/latticedb/models")
    assert r.status_code == 200
    body = r.json()
    assert "items" in body and isinstance(body["items"], list)
    assert len(body["items"]) >= 1
    required = {"id", "hf", "dim", "license", "prompt_format"}
    for item in body["items"]:
        assert required.issubset(item.keys())
        assert isinstance(item["id"], str)
        assert isinstance(item["hf"], str)
        assert isinstance(item["dim"], int)
        assert isinstance(item["license"], str)
        assert isinstance(item["prompt_format"], dict)
