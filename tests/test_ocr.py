import pytest
from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)


def test_extract_screenshot_empty_payload():
    response = client.post("/api/extract-screenshot", json={"image_data": ""})
    assert response.status_code == 400


def test_extract_screenshot_invalid_base64():
    response = client.post("/api/extract-screenshot", json={"image_data": "invalid_data"})
    assert response.status_code == 400


def test_ut_course_lookup_expanded_catalog():
    # Test FSSI4206 (KRS code) and FSSI4316 (Bahan ajar code)
    res1 = client.get("/api/ut-course-lookup?query=FSSI4206")
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["found"] is True
    assert "Morpho-Syntax" in data1["course"]["nama"]

    res2 = client.get("/api/ut-course-lookup?query=FSSI4316")
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["found"] is True
    assert "Morpho-Syntax" in data2["course"]["nama"]
