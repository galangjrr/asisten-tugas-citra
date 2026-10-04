import os
import json
import pytest
from tools.module_library import list_saved_modules, load_saved_module, get_saved_modules_dirs
from fastapi.testclient import TestClient
from api.main import app


def test_saved_modules_dirs_exist():
    dirs = get_saved_modules_dirs()
    assert len(dirs) >= 1
    # Salah satu direktori harus memuat saved_modules
    assert any("saved_modules" in d for d in dirs)


def test_list_saved_modules_finds_fssi4105():
    modules = list_saved_modules()
    assert len(modules) >= 1
    # Modul FSSI4105 harus terdeteksi di direktori
    found = any("FSSI4105" in m["title"] or "FSSI4105" in m["filename"] for m in modules)
    assert found, "Modul FSSI4105 harus ditemukan di pustaka modul tersimpan"


def test_load_saved_module_fssi4105():
    data = load_saved_module("FSSI4105_Pengantar_Linguistik_Umum")
    assert data is not None
    assert "FSSI4105" in data["title"]
    assert len(data.get("pages_content", [])) > 0
    assert any("Djatmika" in author for author in data.get("authors", []))


def test_api_saved_modules_list_and_load():
    client = TestClient(app)
    
    # 1. GET /api/saved-modules
    res = client.get("/api/saved-modules")
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert body["total"] >= 1
    assert any("FSSI4105" in m["title"] for m in body["modules"])
    
    # 2. POST /api/saved-modules/load
    load_res = client.post("/api/saved-modules/load", json={"module_id": "FSSI4105_Pengantar_Linguistik_Umum"})
    assert load_res.status_code == 200
    paper_item = load_res.json()
    assert "FSSI4105" in paper_item["title"]
    assert paper_item["is_ut_bmp"] is True
