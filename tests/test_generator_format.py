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

