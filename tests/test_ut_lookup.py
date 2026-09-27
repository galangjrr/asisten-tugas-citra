import pytest
from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)


def test_ut_course_lookup_exact():
    # Test kode FSSI4106
    response = client.get("/api/ut-course-lookup?query=FSSI4106")
    assert response.status_code == 200
    data = response.json()
    assert data["found"] is True
    assert data["exact"] is True
    assert data["course"]["kode"] == "FSSI4106"
    assert "English for Translation" in data["course"]["nama"]
    assert "Edisi 1" in data["course"]["edisi"]


def test_ut_course_lookup_with_space_and_lowercase():
    # Test lowercase dan spasi 'ekma 4116'
    response = client.get("/api/ut-course-lookup?query=ekma 4116")
    assert response.status_code == 200
    data = response.json()
    assert data["found"] is True
    assert data["exact"] is True
    assert data["course"]["kode"] == "EKMA4116"
    assert "Manajemen" in data["course"]["nama"]


def test_ut_course_lookup_partial_suggestions():
    # Test kueri sebagian 'translation'
    response = client.get("/api/ut-course-lookup?query=translation")
    assert response.status_code == 200
    data = response.json()
    assert data["found"] is True
    assert len(data["suggestions"]) > 0


def test_ut_course_lookup_empty_or_short():
    response = client.get("/api/ut-course-lookup?query=x")
    assert response.status_code == 200
    data = response.json()
    assert data["found"] is False
    assert data["course"] is None
