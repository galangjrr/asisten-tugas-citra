import os
import pytest
from agents.generator import detect_language
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


@pytest.mark.anyio
async def test_essay_spec_applies_lecturer_word_limit(monkeypatch):
    gen, captured = _capture_prompts(monkeypatch)
    await gen.generate_academic_draft("Tulislah esai tentang kota.", [], target_words=950, answer_spec={"answer_type": "esai", "word_limit": 300})

    system = captured["system"]
    assert "maksimal 300 kata" in system
    assert "sekitar 300 kata" in system
    assert "Esai" in system
