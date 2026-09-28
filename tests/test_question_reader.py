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




def test_split_ut_tutorial_sheet_with_metadata_header():
    from tools.question_reader import split_questions_and_guidelines
    sample_text = """FSSI4106 / English for Translation
Tutorial Assignment I - Session 3
Program Studi : Sastra Inggris
Butir Soal No. : 1 dan 2
Skor Maks : 100
Capaian Pembelajaran
Mahasiswa mampu menerjemahkan percakapan tertulis secara wajar.
Petunjuk:
• Terjemahkan setiap percakapan secara utuh ke dalam bahasa Indonesia.

FSSI4106 / English for Translation
Tutorial Assignment I - Session 3
SOAL TUGAS TUTORIAL I
1. Translate the following written conversation into Indonesian! (Score 50)
Guest Good evening. I have a reservation.
Total Score: 100"""
    result = split_questions_and_guidelines(sample_text)
    assert "Translate the following" in result["questions"]
    assert "Guest Good evening" in result["questions"]
    for noise in ("Program Studi", "Butir Soal No.", "Petunjuk", "Capaian", "English for Translation", "Total Score"):
        assert noise not in result["questions"]
    assert "Terjemahkan setiap percakapan" in result["guidelines"]
    assert "Capaian Pembelajaran" in result["guidelines"]
    assert "Total Score: 100" in result["guidelines"]
    assert "English for Translation" not in result["guidelines"]


def test_guess_answer_spec_for_translation_sheet():
    from tools.question_reader import guess_answer_spec
    questions = """1. Translate the following written conversation into Indonesian! (Score 50)
Guest Good evening.
2. Translate the following written conversation into Indonesian! (Score 50)
Host Welcome."""
    spec = guess_answer_spec(questions, "Petunjuk: Terjemahkan setiap percakapan secara utuh.")
    assert spec == {
        "question_count": 2,
        "answer_type": "terjemahan",
        "needs_citations": False,
        "answer_language": "id",
        "word_limit": None,
    }


def test_guess_answer_spec_for_essay_with_citations():
    from tools.question_reader import guess_answer_spec
    spec = guess_answer_spec("Write an essay about urban living.", "Use at least two references. Maximum 250-300 words.")
    assert spec["answer_type"] == "esai"
    assert spec["needs_citations"] is True
    assert spec["word_limit"] == 300
    assert spec["question_count"] is None


def test_normalize_answer_spec_rejects_invalid_ai_values():
    from tools.question_reader import normalize_answer_spec
    raw = {"question_count": "999", "answer_type": "puisi", "needs_citations": "ya", "answer_language": "fr", "word_limit": 500}
    spec = normalize_answer_spec(raw, "1. Jelaskan A\n2. Jelaskan B")
    assert spec["question_count"] == 2
    assert spec["answer_type"] == "jawaban_bernomor"
    assert spec["needs_citations"] is None
    assert spec["answer_language"] is None
    assert spec["word_limit"] == 500


def _numbered_paragraph(doc, text, num_id):
    """Paragraf dengan penomoran otomatis Word langsung di paragraf, seperti hasil tombol Numbering."""
    import copy
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    p = doc.add_paragraph(text)
    num_pr = OxmlElement("w:numPr")
    ilvl = OxmlElement("w:ilvl")
    ilvl.set(qn("w:val"), "0")
    num = OxmlElement("w:numId")
    num.set(qn("w:val"), num_id)
    num_pr.append(ilvl)
    num_pr.append(num)
    p._p.get_or_add_pPr().append(copy.deepcopy(num_pr))
    return p


def test_read_docx_restores_list_numbers_in_document_order():
    from docx.oxml.ns import qn
    from tools.question_reader import read_docx_file, count_numbered_questions, guess_answer_spec
    doc = docx.Document()
    num_id = doc.styles["List Number"].element.pPr.find(qn("w:numPr")).find(qn("w:numId")).get(qn("w:val"))

    doc.add_paragraph("LEMBAR SOAL TUGAS TUTORIAL I")
    table = doc.add_table(rows=1, cols=1)
    table.cell(0, 0).text = "Indikator\t:\tMahasiswa mampu menemukan informasi dalam teks."
    doc.add_paragraph("Read the following questions. Then, scan the passage to find the answers.")
    _numbered_paragraph(doc, "Who built the tower?", num_id)
    _numbered_paragraph(doc, "How many people live there?", num_id)
    doc.add_paragraph("The tower was begun in 1066 by William the Conqueror.")

    stream = io.BytesIO()
    doc.save(stream)
    text = read_docx_file(stream.getvalue())

    # Tabel dibaca di posisinya, bukan ditumpuk di akhir dokumen
    assert text.index("Indikator") < text.index("Read the following")
    assert "1. Who built the tower?" in text
    assert "2. How many people live there?" in text
    assert count_numbered_questions(text) == 2

    spec = guess_answer_spec(text)
    assert spec["answer_type"] == "jawaban_singkat"
    assert spec["needs_citations"] is False


def test_count_numbered_questions_multi_part_sheet_is_not_locked():
    from tools.question_reader import count_numbered_questions
    sheet = "Answer the questions.\n1. Who?\n2. Where?\nTrue or false.\n1. The tower is old.\n2. The tower is new."
    assert count_numbered_questions(sheet) == 0
