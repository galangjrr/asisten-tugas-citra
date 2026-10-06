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


def test_frontend_files_are_always_revalidated():
    # Tampilan lama tidak boleh nyangkut di cache setelah aplikasi diperbarui
    assert client.get("/static/theme.css").headers["cache-control"] == "no-cache"
    assert client.get("/").headers["cache-control"] == "no-cache"
    assert "cache-control" not in client.get("/api/health").headers
