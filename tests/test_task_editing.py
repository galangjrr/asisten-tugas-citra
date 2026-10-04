from docx import Document
from fastapi.testclient import TestClient
from api.main import app
from api import routes

client = TestClient(app)


def make_task(task_id: str) -> None:
    task = {
        "title": "Tugas 1",
        "sections": [
            {"heading": "1. Deskripsi", "content": "Isi lama satu."},
            {"heading": "2. Surat", "content": "Isi lama dua."},
        ],
        "references": [],
        "language": "id",
        "identity_lines": ["Nama: Citra"],
        "topic": "1. Deskripsikan kedai.\n2. Tulis surat.",
        "guidelines": "",
        "answer_spec": {"item_word_limits": [None, 250]},
        "course_name": "Writing",
        "student_name": "Citra",
        "student_id": "0412",
    }
    routes.build_task_files(task_id, task)
    routes.TASKS_DB[task_id] = task


def test_manual_edit_rebuilds_files():
    make_task("edit1")
    res = client.put("/api/tasks/edit1", json={
        "title": "Tugas Baru",
        "sections": [{"heading": "1. Deskripsi", "content": "Isi baru hasil edit."}, {"heading": "2. Surat", "content": "Isi lama dua."}],
    })
    assert res.status_code == 200
    assert res.json()["word_count"] == 7
    text = [p.text for p in Document(routes.TASKS_DB["edit1"]["docx_path"]).paragraphs]
    assert "Isi baru hasil edit." in text and "TUGAS BARU" in text
    assert routes.TASKS_DB["edit1"]["download_base"] == "Tugas Baru_Writing_Citra_0412"

    assert client.put("/api/tasks/edit1", json={"title": "", "sections": []}).status_code == 422
    assert client.put("/api/tasks/tidakada", json={"title": "A", "sections": [{"content": "B"}]}).status_code == 404


def test_rewrite_only_touches_one_section(monkeypatch):
    make_task("rw1")
    seen = {}

    async def fake_rewrite(**kwargs):
        seen.update(kwargs)
        return {"heading": "2. Surat", "content": "Surat versi baru."}

    monkeypatch.setattr(routes, "rewrite_section", fake_rewrite)
    res = client.post("/api/tasks/rw1/sections/1/rewrite", json={"instruction": "lebih santai"})
    assert res.status_code == 200
    sections = res.json()["sections"]
    assert sections[0]["content"] == "Isi lama satu."
    assert sections[1]["content"] == "Surat versi baru."
    # Batas kata soal 2 dan nama penanda tangan ikut diteruskan ke Gemini
    assert seen["word_limit"] == 250 and seen["student_name"] == "Citra" and seen["instruction"] == "lebih santai"

    assert client.post("/api/tasks/rw1/sections/5/rewrite", json={}).status_code == 400


def test_download_after_restart_loads_task_from_disk():
    make_task("unduh1")
    routes.save_task_to_disk("unduh1", routes.TASKS_DB["unduh1"])
    # Aplikasi dibuka ulang: memori kosong, tugas cuma ada di disk
    routes.TASKS_DB.pop("unduh1")
    res = client.get("/api/download/docx/unduh1")
    assert res.status_code == 200
    assert res.content[:2] == b"PK"
    assert client.get("/api/download/pdf/tidakada").status_code == 404
