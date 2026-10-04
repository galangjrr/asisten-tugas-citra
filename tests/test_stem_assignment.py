import json

import pytest
from google.genai import types

from agents.generator import clean_output_text
from tools.question_reader import guess_answer_spec, is_stem_question

STEM_QUESTIONS = {
    "algoritma": "1. Tentukan kompleksitas waktu algoritma merge sort dalam notasi Big O dan jelaskan relasi rekursifnya.",
    "aljabar linear": "1. Diketahui matriks A = [[2, 1], [1, 3]]. Hitunglah determinan dan invers matriks A.",
    "statistika": "1. Data nilai: 70, 80, 90. Hitunglah rata-rata dan standar deviasi, lalu lakukan uji t terhadap hipotesis nol.",
    "listrik magnet": "1. Sebuah kapasitor 10 μF dihubungkan ke sumber 12 Volt. Hitunglah muatan dalam Coulomb.",
}


def test_stem_domain_classification():
    for domain, question in STEM_QUESTIONS.items():
        assert is_stem_question(question), domain
        assert guess_answer_spec(question)["is_mathematical"] is True, domain

    # Kata eksakta yang lewat di soal sosial atau sastra tidak boleh mengubah jawaban jadi hitungan
    assert not is_stem_question("Jelaskan peran audit sektor publik tahun 2020-2021.")
    assert not is_stem_question("Jelaskan persamaan dan perbedaan tokoh Kakek dan Ajo Sidi.")
    assert not is_stem_question("Apa makna simbol surau dalam cerpen tersebut?")
    # Esai tetap esai walau menyebut istilah matematika
    essay = guess_answer_spec("Tulis esai tentang manfaat matriks dan regresi dalam ekonomi.")
    assert essay["answer_type"] == "esai" and essay["is_mathematical"] is False


def _capture(monkeypatch, content):
    import agents.generator as gen
    captured = {}

    async def fake_generate(category, contents, config=None, **kwargs):
        captured["system"] = config.system_instruction
        captured["thinking"] = config.thinking_config
        text = json.dumps({"title": "T", "sections": [{"heading": "1. Determinan dan Invers", "content": content}]})
        return type("Res", (), {"text": text})()

    monkeypatch.setattr(gen, "generate_with_fallback", fake_generate)
    return gen, captured


@pytest.mark.anyio
async def test_stem_four_pillar_structure(monkeypatch):
    # Model bandel tetap mengirim LaTeX, keluaran akhir wajib bersih untuk Word dan PDF
    raw = (
        "Diketahui: A berordo 2 × 2\nDitanya: det(A) dan A⁻¹\n"
        "Rumus: det(A) = ad - bc\n"
        "Penyelesaian:\ndet(A) = 2 × 3 - 1 × 1 = 5\n"
        "$A^{-1} = \\frac{1}{5} \\begin{bmatrix} 3 & -1 \\\\ -1 & 2 \\end{bmatrix}$\n"
        "Jawaban: det(A) = 5"
    )
    gen, captured = _capture(monkeypatch, raw)
    result = await gen.generate_academic_draft(STEM_QUESTIONS["aljabar linear"], [], answer_spec={"answer_type": "uraian"})

    system = captured["system"]
    assert "PROTOKOL SOAL HITUNGAN EKSAKTA" in system
    for label in ("Diketahui:", "Ditanya:", "Rumus:", "Penyelesaian:", "Jawaban:"):
        assert label in system
    assert "substitusikan balik" in system and "' | '" in system
    assert captured["thinking"].thinking_level == types.ThinkingLevel.HIGH

    content = result["sections"][0]["content"]
    assert "Diketahui" in content and "Ditanya" in content
    assert content.count("\n") >= 5
    assert "3 | -1" in content and "-1 | 2" in content
    assert "\\frac" not in content and "\\begin" not in content and "$" not in content
    assert "(1)/(5)" in content


@pytest.mark.anyio
async def test_essay_skips_stem_protocol(monkeypatch):
    gen, captured = _capture(monkeypatch, "x")
    await gen.generate_academic_draft("Tulis esai tentang manfaat matriks dan regresi dalam ekonomi.", [], answer_spec={"answer_type": "esai"})
    assert "PROTOKOL SOAL HITUNGAN EKSAKTA" not in captured["system"]


def test_latex_cleanup_keeps_currency_and_plain_text():
    assert clean_output_text("Harga $5 naik jadi $ 10") == "Harga $5 naik jadi $ 10"
    assert clean_output_text(r"$\sqrt{16} \leq 5 \times 2$") == "√(16) ≤ 5 × 2"
    assert clean_output_text("Tanpa LaTeX tetap sama.") == "Tanpa LaTeX tetap sama."
