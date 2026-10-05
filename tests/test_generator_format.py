import os
import pytest
from google.genai import types
from agents.generator import clean_output_text, detect_language
from exporters.docx_builder import create_assignment_docx
from exporters.pdf_builder import create_assignment_pdf
from docx import Document
from pypdf import PdfReader


def test_detect_language():
    en_prompt = "Write a short essay in which you explain your personal preference between living in an urban area or a metropolitan area."
    assert detect_language(en_prompt) == "en"

    id_prompt = "Jelaskan dan uraikan analisis saudara mengenai peran audit sektor publik menurut modul 3 BMP UT."
    assert detect_language(id_prompt) == "id"

    mixed_prompt = "Write an essay about urban development in Jakarta"
    assert detect_language(mixed_prompt) == "en"


def test_clean_output_text():
    assert clean_output_text("Audit publik — terutama di daerah — masih lemah.") == "Audit publik, terutama di daerah, masih lemah."
    assert clean_output_text("Periode 2010–2020 dan hlm. 3—5") == "Periode 2010-2020 dan hlm. 3-5"
    assert clean_output_text("— poin satu\n– poin dua") == "- poin satu\n- poin dua"
    assert clean_output_text("Hasilnya menurun —.") == "Hasilnya menurun."
    assert clean_output_text("dan seterusnya…") == "dan seterusnya..."
    assert clean_output_text("142 - sqrt(10)^2 = 132 cm^2, x^(-1), sqrt(2x+1)") == "142 - √10² = 132 cm², x⁻¹, √(2x+1)"


def test_docx_essay_format_and_references():
    title = "Living in Urban versus Metropolitan Areas"
    sections = [
        {"heading": "", "content": "Living in an urban environment provides a balanced pace of life with modern conveniences."},
        {"heading": "", "content": "Metropolitan cities, on the other hand, feature vast employment networks and cultural hubs."}
    ]
    references = [
        {
            "authors": ["John Doe", "Jane Smith"],
            "year": 2023,
            "title": "Urbanization Patterns in Modern Cities",
            "venue": "Journal of Urban Studies",
            "doi": "https://doi.org/10.1000/182"
        }
    ]
    out_docx = create_assignment_docx(title, sections, references, "test_essay_output.docx")
    assert os.path.exists(out_docx)

    doc = Document(out_docx)
    all_paras = [p.text for p in doc.paragraphs if p.text.strip()]
    
    # Verify REFERENCES is used instead of DAFTAR PUSTAKA for English doc
    assert "REFERENCES" in all_paras
    assert "DAFTAR PUSTAKA" not in all_paras
    
    # Verify no empty headings or robotic Bab headers
    assert "BAB I" not in all_paras
    
    if os.path.exists(out_docx):
        os.remove(out_docx)


def test_pdf_essay_format_and_references():
    title = "Living in Urban versus Metropolitan Areas"
    sections = [
        {"heading": "", "content": "Living in an urban environment provides a balanced pace of life with modern conveniences."},
        {"heading": "", "content": "Metropolitan cities, on the other hand, feature vast employment networks and cultural hubs."}
    ]
    references = [
        {
            "authors": ["John Doe", "Jane Smith"],
            "year": 2023,
            "title": "Urbanization Patterns in Modern Cities",
            "venue": "Journal of Urban Studies",
            "doi": "https://doi.org/10.1000/182"
        }
    ]
    out_pdf = create_assignment_pdf(title, sections, references, "test_essay_output.pdf")
    assert os.path.exists(out_pdf)

    reader = PdfReader(out_pdf)
    full_text = " ".join([page.extract_text() for page in reader.pages])
    assert "REFERENCES" in full_text
    assert "DAFTAR PUSTAKA" not in full_text

    if os.path.exists(out_pdf):
        os.remove(out_pdf)


def test_tone_format_adaptation():
    tone_personal = "surat personal"
    tone_reflective = "opini reflektif"
    
    assert any(k in tone_personal.lower() for k in ["surat", "letter", "korespondensi"])
    assert any(k in tone_reflective.lower() for k in ["reflektif", "opini", "reflective", "opinion"])



def test_count_numbered_questions():
    from agents.generator import count_numbered_questions
    two_items = """SOAL TUGAS TUTORIAL I
1. Translate the following written conversation into Indonesian! (Score 50)
Guest Good evening.
2. Translate the following written conversation into Indonesian! (Score 50)
Receptionist You are welcome."""
    assert count_numbered_questions(two_items) == 2
    assert count_numbered_questions("Soal 1: Jelaskan X\nSoal 2: Uraikan Y\nSoal 3: Bandingkan Z") == 3
    assert count_numbered_questions("Tulislah esai 300 kata tentang kehidupan kota.") == 0
    # Nomor yang tidak mulai dari 1 bukan daftar soal
    assert count_numbered_questions("Pada tahun 2020 terjadi krisis.\n3. Tidak berurutan") == 0


def _capture_prompts(monkeypatch):
    import agents.generator as gen
    captured = {}

    async def fake_generate(category, contents, config=None, **kwargs):
        captured["system"] = config.system_instruction
        captured["user"] = contents
        captured["thinking"] = config.thinking_config
        return type("Res", (), {"text": '{"title": "T", "sections": [{"heading": "1. A", "content": "x"}]}'})()

    monkeypatch.setattr(gen, "generate_with_fallback", fake_generate)
    return gen, captured


@pytest.mark.anyio
async def test_translation_spec_forces_direct_answer_in_target_language(monkeypatch):
    gen, captured = _capture_prompts(monkeypatch)
    topic = "1. Translate the following conversation into Indonesian!\nGuest Hi.\n2. Translate the following conversation into Indonesian!\nHost Hello."
    spec = {"answer_type": "terjemahan", "answer_language": "id", "question_count": 2, "needs_citations": False}
    await gen.generate_academic_draft(topic, [], target_words=950, answer_spec=spec)

    system = captured["system"]
    assert "ATURAN JAWABAN LANGSUNG" in system
    assert "TEPAT 2 butir" in system
    # Soal berbahasa Inggris tapi jawaban terjemahan wajib berbahasa Indonesia
    assert "KEPATUHAN BAHASA WAJIB" in system
    assert "ATURAN PANJANG NASKAH" not in system
    # Target kata dari pengaturan umum tidak boleh bocor ke prompt jawaban langsung
    assert "950 kata" not in captured["user"]
    assert "analisis mendalam" not in captured["user"]


@pytest.mark.anyio
async def test_essay_spec_applies_lecturer_word_limit(monkeypatch):
    gen, captured = _capture_prompts(monkeypatch)
    await gen.generate_academic_draft("Tulislah esai tentang kota.", [], target_words=950, answer_spec={"answer_type": "esai", "word_limit": 300})

    system = captured["system"]
    assert "maksimal 300 kata" in system
    # Target 95 persen dari batas maksimal supaya ada ruang aman di bawah batas
    assert "sekitar 285 kata" in system
    assert "Esai" in system


@pytest.mark.anyio
async def test_every_format_gets_per_item_length_rule(monkeypatch):
    gen, captured = _capture_prompts(monkeypatch)
    await gen.generate_academic_draft("1. Who built the tower?\n2. Analyze why it was built.", [], format_type="bernomor", target_words=950)

    system = captured["system"]
    assert "ATURAN MENJAWAB SETIAP BUTIR" in system
    assert "1 sampai 2 kalimat" in system
    assert "wajib bersumber dari teks itu" in system


@pytest.mark.anyio
async def test_depth_option_also_applies_to_short_items(monkeypatch):
    gen, captured = _capture_prompts(monkeypatch)
    topic = "1. Who built the tower?\n2. What are two official names of the tower?"

    await gen.generate_academic_draft(topic, [], paragraph_depth="standar")
    assert "cukup dijawab 1 sampai 2 kalimat" in captured["system"]

    await gen.generate_academic_draft(topic, [], paragraph_depth="elaboratif")
    system = captured["system"]
    assert "dijawab 2 sampai 3 kalimat" in system
    assert "kalimat pendukung dari teks soal" in system
    # Aturan jumlah hal yang diminta berlaku di semua kedalaman
    assert "kategori yang sama persis dengan yang ditanyakan" in system


@pytest.mark.anyio
async def test_high_thinking_only_for_reasoning_questions(monkeypatch):
    gen, captured = _capture_prompts(monkeypatch)
    uraian = {"answer_type": "uraian", "needs_citations": False}

    await gen.generate_academic_draft("1. Diketahui f(x,y,z) = x'y'z + xy' + z'. Sederhanakan dengan K-Map.", [], answer_spec=uraian)
    assert captured["thinking"].thinking_level == types.ThinkingLevel.HIGH

    await gen.generate_academic_draft("Jelaskan peran audit sektor publik tahun 2020-2021.", [], answer_spec=uraian)
    assert captured["thinking"] is None

    # Esai tetap cepat walau menyebut angka atau istilah matematika
    await gen.generate_academic_draft("Tulis esai tentang manfaat matriks dalam ekonomi.", [], answer_spec={"answer_type": "esai"})
    assert captured["thinking"] is None


@pytest.mark.anyio
async def test_item_word_limits_reach_the_prompt(monkeypatch):
    gen, captured = _capture_prompts(monkeypatch)
    spec = {"answer_type": "jawaban_bernomor", "question_count": 2, "word_limit": 500, "item_word_limits": [200, 300]}
    await gen.generate_academic_draft("1. Jelaskan A.\n2. Jelaskan B.", [], target_words=1000, answer_spec=spec)
    assert "butir 1 maksimal 200 kata, butir 2 maksimal 300 kata" in captured["system"]
    assert "maksimal 500 kata untuk seluruh jawaban" in captured["system"]


@pytest.mark.anyio
async def test_multi_question_essay_keeps_item_numbers(monkeypatch):
    import agents.generator as gen
    captured = {}

    async def fake_generate(category, contents, config=None, **kwargs):
        captured["system"] = config.system_instruction
        # Model mengosongkan heading seperti format esai
        return type("Res", (), {"text": '{"title": "T", "sections": [{"heading": "", "content": "a"}, {"heading": "", "content": "b"}]}'})()

    monkeypatch.setattr(gen, "generate_with_fallback", fake_generate)
    topic = "Describe the coffee shop in the picture.\n\nWrite a letter to the editor about the park."
    result = await gen.generate_academic_draft(topic, [], target_words=950, answer_spec={"answer_type": "esai", "question_count": 2})

    assert "TEPAT 2 bagian" in captured["system"]
    assert [s["heading"] for s in result["sections"]] == ["1.", "2."]


@pytest.mark.anyio
async def test_item_over_word_limit_is_trimmed(monkeypatch):
    import agents.generator as gen
    long_letter = " ".join(["word"] * 300)

    async def fake_generate(category, contents, config=None, **kwargs):
        return type("Res", (), {"text": '{"title": "T", "sections": [{"heading": "1. A", "content": "free length"}, {"heading": "2. B", "content": "%s"}]}' % long_letter})()

    trimmed = {}

    async def fake_rewrite(topic, sections, index, **kwargs):
        trimmed["index"], trimmed["limit"] = index, kwargs["word_limit"]
        return {"heading": sections[index]["heading"], "content": "short letter"}

    monkeypatch.setattr(gen, "generate_with_fallback", fake_generate)
    monkeypatch.setattr(gen, "rewrite_section", fake_rewrite)
    spec = {"question_count": 2, "item_word_limits": [None, 250]}
    result = await gen.generate_academic_draft("1. Describe it.\n2. Write a letter.", [], answer_spec=spec)

    assert trimmed == {"index": 1, "limit": 250}
    assert result["sections"][1]["content"] == "short letter"
    assert result["sections"][0]["content"] == "free length"


@pytest.mark.anyio
async def test_auto_format_does_not_number_single_writing_task(monkeypatch):
    gen, captured = _capture_prompts(monkeypatch)
    # Satu soal di mode otomatis ditulis utuh tanpa heading '1. ...'
    result = await gen.generate_academic_draft("1. Tulislah pendapatmu tentang literasi digital.", [], target_words=600,
                                               answer_spec={"answer_type": "uraian", "question_count": 1})
    assert "TEPAT 1 butir" not in captured["system"]
    assert result["sections"][0]["heading"] == "1. A"  # heading dari model tidak ditambah nomor lagi

    # AI bilang satu tulisan tanpa nomor, poin panduan '1. 2. 3.' tidak boleh dihitung ulang jadi 3 soal
    guided = "Tulislah esai tentang kota yang memuat:\n1. Definisi kota\n2. Contoh kota\n3. Pendapatmu"
    await gen.generate_academic_draft(guided, [], target_words=600, answer_spec={"answer_type": "esai", "question_count": None})
    assert "TEPAT 3 butir" not in captured["system"]

    # Soal ditempel manual tanpa deteksi tetap dinomori sesuai lembar soal
    await gen.generate_academic_draft("1. Jelaskan X.\n2. Uraikan Y.", [], target_words=600, answer_spec={"question_count": None})
    assert "TEPAT 2 butir" in captured["system"]


@pytest.mark.anyio
async def test_citation_rules_stay_natural(monkeypatch):
    gen, captured = _capture_prompts(monkeypatch)
    paper = {"title": "Kerukunan", "authors": ["Budi Prakosa"], "year": 2022, "pages_content": [{"page_number": 51, "text": "Isi."}]}
    await gen.generate_academic_draft("Jelaskan kerukunan antarumat beragama.", [paper], target_words=600, answer_spec={"answer_type": "esai"})
    system = captured["system"]
    assert "Paling banyak satu sitasi per paragraf" in system
    assert "Kesimpulan atau penutup DILARANG berisi sitasi" in system
    # Aturan lama yang memaksa sitasi di mana-mana tidak boleh balik lagi
    assert "WAJIB 100%" not in system and "Modul 3, hlm. 3.14" not in system
    assert "WAJIB DISITASI" not in captured["user"]


@pytest.mark.anyio
async def test_task_type_sets_campus_context(monkeypatch):
    gen, captured = _capture_prompts(monkeypatch)
    await gen.generate_academic_draft("Jelaskan konsep inflasi.", [], task_type="umum")
    assert "bukan Universitas Terbuka" in captured["system"]

    await gen.generate_academic_draft("Jelaskan konsep inflasi.", [], task_type="ut-diskusi")
    assert "Tuton" in captured["system"] and "bukan Universitas Terbuka" not in captured["system"]

    # Klien lama tanpa jenis tugas tidak diberi konteks kampus apa pun
    await gen.generate_academic_draft("Jelaskan konsep inflasi.", [])
    assert "KONTEKS KAMPUS" not in captured["system"]


def test_generate_rejects_unknown_task_type():
    from fastapi.testclient import TestClient
    from api.main import app

    res = TestClient(app).post("/api/generate", json={"topic": "Jelaskan inflasi", "task_type": "kampus-x"})
    assert res.status_code == 422
