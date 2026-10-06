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


def test_roman_numbering_counts_when_no_digits():
    assert count_numbered_questions("I. Jelaskan A.\nII. Uraikan B.\nIII. Bandingkan C.\nIV. Simpulkan D.") == 4
    # Sub-soal huruf di bawah nomor romawi tidak ikut dihitung
    assert count_numbered_questions("I. Soal satu\na. bagian a\nb. bagian b\nII. Soal dua") == 2
    # Nomor angka tetap lebih kuat dari romawi
    assert count_numbered_questions("I. Kasus\n1. Jelaskan A.\n2. Uraikan B.\n3. Analisis C.") == 3


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
    result = await gen.generate_academic_draft(questions, [paper], target_words=800, answer_spec=spec, quote_citations=True)

    system = captured["system"]
    assert "TEPAT 2 bagian" in system and "DILARANG menggabung dua nomor" in system
    assert "ATURAN KUTIPAN LANGSUNG" in system and "sesuai label halaman" in system
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


@pytest.mark.anyio
async def test_text_fidelity_rules_are_general_for_any_reading(monkeypatch):
    import agents.generator as gen
    # Aturan berupa prinsip umum, tidak menyebut tokoh atau judul cerita tertentu
    for name in ("William", "Crawford", "Helen", "Burglar", "Navis", "Ajo Sidi"):
        assert name not in gen.TEXT_FIDELITY_RULES
    for principle in ("narator", "nama samaran", "Pertanyaan tidak boleh ditulis sebagai tuntutan", "tafsiran"):
        assert principle in gen.TEXT_FIDELITY_RULES

    # Berlaku di soal sastra, kasus hukum, maupun soal tanpa rujukan
    gen_mod, captured = _capture(monkeypatch, '{"title": "T", "sections": [{"heading": "1. A", "content": "x"}]}')
    for topic, papers in [
        ("1. Analisis watak tokoh utama dalam drama berikut.", []),
        ("Uraikan posisi para pihak dalam kasus berikut beserta bunyi pasalnya.", [{"title": "Putusan", "authors": ["MA"], "year": 2020, "pages_content": [{"page_number": 2, "text": "Isi."}]}]),
    ]:
        await gen_mod.generate_academic_draft(topic, papers, answer_spec={"answer_type": "uraian"})
        assert "ATURAN SETIA PADA TEKS SUMBER" in captured["system"]


@pytest.mark.anyio
async def test_rewrite_section_sees_source_text_and_fidelity_rules(monkeypatch):
    import agents.generator as gen
    captured = {}

    async def fake_generate(category, contents, config=None, **kwargs):
        captured["system"], captured["user"] = config.system_instruction, contents
        return type("Res", (), {"text": '{"content": "baru"}'})()

    monkeypatch.setattr(gen, "generate_with_fallback", fake_generate)
    paper = {"title": "Cerpen", "authors": ["Penulis Contoh"], "year": 1900, "is_manual_module": True,
             "pages_content": [{"page_number": "Halaman 3", "text": "Kalimat asli di halaman tiga."}]}
    sections = [{"heading": "1. A", "content": "lama"}]
    result = await gen.rewrite_section("1. Analisis tokoh.", sections, 0, papers=[paper])

    assert result["content"] == "baru"
    assert "ATURAN SETIA PADA TEKS SUMBER" in captured["system"]
    assert "disalin persis dari BAHAN SUMBER" in captured["system"]
    assert "[Halaman 3]: Kalimat asli di halaman tiga." in captured["user"]


def test_strip_quote_citations_keeps_quotes_and_paraphrase_citations():
    from agents.generator import strip_quote_citations
    text = (
        'Ia berkata, "I am a common thief!" (Cather, 1896, hlm. 5). '
        'Ibunya menjawab, "they are all yours" (Cather, 1896, hlm. 5). '
        'Lalu "love has nothing to do with pardon?" (Cather, 1896/2024, hlm. 7) menutup dialog. '
        'Teori ini umum dipakai (Wellek & Warren, 1949). Kutipan daring "tanpa tahun" (Anonim, n.d.).'
    )
    assert strip_quote_citations(text) == (
        'Ia berkata, "I am a common thief!" '
        'Ibunya menjawab, "they are all yours". '
        'Lalu "love has nothing to do with pardon?" menutup dialog. '
        'Teori ini umum dipakai (Wellek & Warren, 1949). Kutipan daring "tanpa tahun".'
    )


@pytest.mark.anyio
async def test_quote_citations_are_optional_and_off_by_default(monkeypatch):
    output = '{"title": "T", "sections": [{"heading": "1. A", "content": "Ia berkata, \\"Aku pulang\\" (Navis, 1956, hlm. 3). Itu tandanya (Navis, 1956)."}]}'
    gen, captured = _capture(monkeypatch, output)
    paper = {"title": "Cerpen", "authors": ["A.A. Navis"], "year": 1956, "is_manual_module": True,
             "pages_content": [{"page_number": "Halaman 3", "text": "Aku pulang."}]}

    result = await gen.generate_academic_draft("1. Analisis tokoh dengan kutipan.", [paper], answer_spec={"answer_type": "jawaban_bernomor"})
    assert "TANPA sitasi dalam kurung" in captured["system"]
    # Kutipan tetap bertanda petik, sitasi kurung setelah kutipan dibuang, sitasi parafrase dibiarkan
    assert result["sections"][0]["content"] == 'Ia berkata, "Aku pulang". Itu tandanya (Navis, 1956).'

    result = await gen.generate_academic_draft("1. Analisis tokoh dengan kutipan.", [paper], answer_spec={"answer_type": "jawaban_bernomor"}, quote_citations=True)
    assert "WAJIB diikuti sitasi dengan halaman" in captured["system"]
    assert "(Navis, 1956, hlm. 3)" in result["sections"][0]["content"]

    # Daftar pustaka saja: semua sitasi kurung dibuang, kutipan dan sumbernya tetap dipakai
    result = await gen.generate_academic_draft("1. Analisis tokoh dengan kutipan.", [paper], answer_spec={"answer_type": "jawaban_bernomor"},
                                               quote_citations=True, citation_style="list_only")
    assert "ATURAN RUJUKAN DAFTAR PUSTAKA SAJA" in captured["system"] and "ATURAN SITASI YANG WAJAR" not in captured["system"]
    assert result["sections"][0]["content"] == 'Ia berkata, "Aku pulang". Itu tandanya.'


def test_in_text_citation_removal_spares_ordinary_parentheses():
    from agents.generator import finalize_text
    text = ("Kerukunan butuh kesadaran bersama (Prakosa, 2022). Dua teori ini saling melengkapi (Ruiz & Lee, 2021; Prakosa dkk., 2022, hlm. 5). "
            "Aturannya ada di undang-undang (UU No. 13 Tahun 2003) dan tabel (lihat Tabel 1).")
    assert finalize_text(text, False, "list_only") == (
        "Kerukunan butuh kesadaran bersama. Dua teori ini saling melengkapi. "
        "Aturannya ada di undang-undang (UU No. 13 Tahun 2003) dan tabel (lihat Tabel 1)."
    )
    # Pilihan biasa tidak menyentuh sitasi parafrase
    assert finalize_text(text, False) == text


def test_cliche_sentence_openers_are_dropped():
    from agents.generator import finalize_text
    text = "Pada akhirnya, media sosial jadi panggung. Secara keseluruhan, ini wajar.\n\nOverall, it works. Ia menyebut pada akhirnya, semua usai."
    assert finalize_text(text, True) == "Media sosial jadi panggung. Ini wajar.\n\nIt works. Ia menyebut pada akhirnya, semua usai."
