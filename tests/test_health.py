from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)


def test_health_check_endpoint():
    """Memastikan endpoint health merespons status 200 dan format data sesuai."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert "gemini_configured" in data
    assert data["version"] == "1.0.0"
