import io
import pytest
from fastapi.testclient import TestClient
import docx
import pypdf
from api.main import app
from tools.question_reader import parse_question_document, extract_course_code_from_text

client = TestClient(app)


def test_extract_course_code():
    text1 = "Tugas 1 Mata Kuliah EKMA4116 Manajemen Semester 2024.1"
    assert extract_course_code_from_text(text1) == "EKMA4116"

    text2 = "Petunjuk Diskusi FSSI 4206 English Syntax"
    assert extract_course_code_from_text(text2) == "FSSI4206"

    text3 = "Tanpa kode disini"
    assert extract_course_code_from_text(text3) is None


@pytest.mark.anyio
async def test_parse_docx_file():
    # Buat dokumen docx in-memory
    doc = docx.Document()
    doc.add_paragraph("Selamat pagi rekan mahasiswa sekalian.")
    doc.add_paragraph("Pertanyaan: Jelaskan perbedaan fonetik dan fonologi menurut modul FSSI4206!")
    
    stream = io.BytesIO()
    doc.save(stream)
    stream.seek(0)
    docx_bytes = stream.read()

    res = await parse_question_document(docx_bytes, "soal_tugas.docx")
    assert res["success"] is True
    assert res["file_type"] == "docx"
    assert "Jelaskan perbedaan fonetik" in res["text"]
    assert res["detected_course_code"] == "FSSI4206"


def test_upload_question_file_endpoint():
    doc = docx.Document()
    doc.add_paragraph("Soal Ujian Akhir Semester: Analisis strategi pemasaran PT ABC.")
    stream = io.BytesIO()
    doc.save(stream)
    stream.seek(0)

    response = client.post(
        "/api/upload-question-file",
        files={"file": ("soal.docx", stream.read(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "Analisis strategi pemasaran" in data["text"]


def test_split_questions_and_guidelines():
    from tools.question_reader import split_questions_and_guidelines
    sample_text = """Petunjuk Pengerjaan Tugas:
1. Gunakan modul 3 BMP EKMA4116.
2. Rubrik penilaian: analisis 50%, kesimpulan 20%.

Soal 1:
Jelaskan konsep segmentasi pasar menurut Kotler!
"""
    result = split_questions_and_guidelines(sample_text)
    assert "Petunjuk Pengerjaan Tugas" in result["guidelines"]
    assert "Rubrik penilaian" in result["guidelines"]
    assert "Soal 1:" in result["questions"]
    assert "Jelaskan konsep segmentasi pasar" in result["questions"]


@pytest.mark.anyio
async def test_bilingual_assignment_parsing():
    indo_text = """TUGAS 1 TUTON UNIVERSITAS TERBUKA
Mata Kuliah: Manajemen Keuangan (EKMA4213)
Selamat pagi rekan mahasiswa.
Petunjuk:
1. Kerjakan minimal 800 kata.
2. Rujuk Modul 3 BMP.
Soal:
1. Jelaskan struktur modal optimal menurut trade-off theory!"""

    res = await parse_question_document(indo_text.encode("utf-8"), "tugas.txt")
    assert res["success"] is True
    assert "trade-off theory" in res["questions"]
    assert res["detected_course_code"] == "EKMA4213"


