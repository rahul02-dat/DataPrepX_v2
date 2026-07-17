from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_healthz_returns_ok():
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "agent-orchestrator"
    assert "ollama_url_configured" in body