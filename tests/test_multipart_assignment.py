import io

import pytest
from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas

from api.main import app
from api.routes import CACHED_PAPERS
from tools.question_reader import count_numbered_questions, normalize_answer_spec, parse_question_document
from tools.reading_doc_reader import read_reading_doc

client = TestClient(app)

COMPOUND_SHEET = """Petunjuk: Kerjakan dengan jujur. Maksimal 800 kata. Skor maksimal 100.
Soal:
1. Jelaskan perubahan karakter Ajo Sidi dalam cerpen Robohnya Surau Kami, sertakan kutipan teks pendukung, lalu sebutkan karakter pilihanmu beserta alasannya.
2. Analisis tema utama cerpen tersebut dan kaitkan dengan kehidupan beragama saat ini."""


def test_compound_question_extraction(monkeypatch):
    # AI salah menghitung soal majemuk sebagai satu butir, nomor eksplisit di teks soal yang menang
    questions = COMPOUND_SHEET.split("Soal:\n", 1)[1]
    spec = normalize_answer_spec({"question_count": 1, "answer_type": "uraian"}, questions)
    assert spec["question_count"] == 2
    assert spec["answer_type"] == "jawaban_bernomor"
    assert spec["is_mathematical"] is False

    # Esai berpoin panduan '1. 2.' tetap satu tulisan
    essay = normalize_answer_spec({"question_count": 1, "answer_type": "esai"}, "Tulis esai yang memuat:\n1. Definisi\n2. Contoh")
    assert essay["question_count"] == 1

    # Pemilah pola tanpa AI: klausul kutipan dan pilihan pribadi tetap di soal, petunjuk administratif ke guidelines
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    import anyio
    res = anyio.run(parse_question_document, COMPOUND_SHEET.encode(), "soal.txt")
    assert "sertakan kutipan teks pendukung" in res["questions"]
    assert "karakter pilihanmu beserta alasannya" in res["questions"]
    assert "Maksimal 800 kata" in res["detected_guidelines"]
    assert "kutipan" not in res["detected_guidelines"]
    assert res["answer_spec"]["question_count"] == 2


def test_letter_numbering_counts_when_no_digits():
    assert count_numbered_questions("a. Jelaskan A.\nb. Uraikan B.\nc. Bandingkan C.") == 3
    # Huruf di bawah nomor angka adalah sub-soal, jadi yang dihitung tetap nomornya
    assert count_numbered_questions("1. Soal satu\na. bagian a\nb. bagian b\n2. Soal dua") == 2


def _capture(monkeypatch, sections_json):
    import agents.generator as gen
    captured = {}

    async def fake_generate(category, contents, config=None, **kwargs):
        captured["system"] = config.system_instruction
        captured["user"] = contents
        return type("Res", (), {"text": sections_json})()

    monkeypatch.setattr(gen, "generate_with_fallback", fake_generate)
    return gen, captured


@pytest.mark.anyio
async def test_direct_quotation_synthesis(monkeypatch):
    model_output = (
        '{"title": "T", "sections": ['
        '{"heading": "1. PERUBAHAN KARAKTER UTAMA", "content": "Kakek berubah. \\"Aku tak pernah mengingat apa-apa\\" (Navis, 1956, hlm. 3). Saya memilih Ajo Sidi karena jujur."},'
        '{"heading": "2. ANALISIS TEMA UTAMA", "content": "Tema utamanya kelalaian sosial."}]}'
    )
    gen, captured = _capture(monkeypatch, model_output)
    paper = {
        "title": "Robohnya Surau Kami", "authors": ["A.A. Navis"], "year": 1956, "is_manual_module": True,
        "pages_content": [{"page_number": "Halaman 3", "text": "Aku tak pernah mengingat apa-apa."}],
    }
    questions = COMPOUND_SHEET.split("Soal:\n", 1)[1]
    spec = {"answer_type": "jawaban_bernomor", "question_count": 2}
    result = await gen.generate_academic_draft(questions, [paper], target_words=800, answer_spec=spec)

    system = captured["system"]
    assert "TEPAT 2 bagian" in system and "DILARANG menggabung dua nomor" in system
    assert "ATURAN KUTIPAN LANGSUNG" in system and "hlm. 3" in system
    assert "Pertanyaan di ujung kalimat soal sama wajibnya" in system
    assert "[Halaman 3]" in captured["user"]
    # Bahan bacaan sastra bukan soal hitungan
    assert "PROTOKOL SOAL HITUNGAN EKSAKTA" not in system

    assert len(result["sections"]) == 2
    first = result["sections"][0]["content"]
    assert '"Aku tak pernah mengingat apa-apa"' in first and "hlm. 3" in first and "Saya memilih" in first


@pytest.mark.anyio
async def test_journal_essay_without_evidence_request_keeps_paraphrase(monkeypatch):
    gen, captured = _capture(monkeypatch, '{"title": "T", "sections": [{"heading": "", "content": "x"}]}')
    paper = {"title": "Kerukunan", "authors": ["Budi Prakosa"], "year": 2022, "pages_content": [{"page_number": 51, "text": "Isi."}]}
    await gen.generate_academic_draft("Jelaskan kerukunan antarumat beragama.", [paper], answer_spec={"answer_type": "esai"})
    assert "ATURAN KUTIPAN LANGSUNG" not in captured["system"]


def _two_page_pdf() -> bytes:
    buf = io.BytesIO()
    pdf = canvas.Canvas(buf)
    pdf.drawString(72, 720, "Halaman pertama cerpen ini bercerita tentang surau tua di kampung.")
    pdf.showPage()
    pdf.drawString(72, 720, "Halaman kedua berisi dialog kakek dengan Ajo Sidi yang membuatnya murung.")
    pdf.save()
    return buf.getvalue()


@pytest.mark.anyio
async def test_reading_pdf_keeps_physical_page_numbers():
    text, used_ocr = await read_reading_doc(_two_page_pdf(), "cerpen.pdf")
    assert not used_ocr
    assert "[Halaman 1]" in text and "[Halaman 2]" in text

    res = client.post("/api/manual-module", json={"module_title": "Robohnya Surau Kami", "author": "A.A. Navis", "year": 1956, "content_text": text})
    assert res.status_code == 200
    pages = CACHED_PAPERS[res.json()["id"]]["pages_content"]
    assert [p["page_number"] for p in pages] == ["Halaman 1", "Halaman 2"]
    assert "Ajo Sidi" in pages[1]["text"] and "[Halaman" not in pages[1]["text"]
    assert "[Halaman" not in res.json()["abstract"]
