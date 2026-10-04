import json

import pytest

from tools.question_reader import extract_word_limit, extract_word_min, guess_answer_spec, normalize_answer_spec

SHEET_GUIDE = "Ketentuan:\n• panjang keseluruhan jawaban minimal 800 kata.\n• gunakan modul 1-3."
QUESTIONS = "1. Jelaskan fonetik.\n2. Jelaskan fonologi.\n3. Jelaskan morfem."


def test_minimum_word_count_is_not_read_as_maximum():
    assert extract_word_min("panjang keseluruhan jawaban minimal 800 kata.") == 800
    assert extract_word_min("Write at least 300 words.") == 300
    assert extract_word_limit("panjang keseluruhan jawaban minimal 800 kata.") is None
    # Batas bawah per soal bukan batas total
    assert extract_word_min("minimal 100 kata per soal") is None
    # Pemisah ribuan ala Indonesia dan Inggris
    assert extract_word_min("paling sedikit 1.000 kata") == 1000
    assert extract_word_limit("maksimal 1.500 kata") == 1500
    assert extract_word_limit("Write 1,200 words") == 1200

    spec = guess_answer_spec(QUESTIONS, SHEET_GUIDE)
    assert spec["word_min"] == 800 and spec["word_limit"] is None


def test_ai_misreading_minimum_as_maximum_is_corrected():
    # AI menaruh 800 di word_limit padahal dosen menulis 'minimal 800 kata'
    spec = normalize_answer_spec({"question_count": 3, "answer_type": "jawaban_bernomor", "word_limit": 800}, QUESTIONS, SHEET_GUIDE)
    assert spec["word_min"] == 800
    assert spec["word_limit"] is None


def _capture(monkeypatch, sections, grown=None):
    import agents.generator as gen
    captured = {"rewrites": []}

    async def fake_generate(category, contents, config=None, **kwargs):
        captured["system"] = config.system_instruction
        return type("Res", (), {"text": json.dumps({"title": "T", "sections": sections})})()

    async def fake_rewrite(topic, secs, index, **kwargs):
        captured["rewrites"].append((index, kwargs["instruction"]))
        return {"heading": secs[index]["heading"], "content": " ".join(["kata"] * (grown or 300))}

    monkeypatch.setattr(gen, "generate_with_fallback", fake_generate)
    monkeypatch.setattr(gen, "rewrite_section", fake_rewrite)
    return gen, captured


@pytest.mark.anyio
async def test_minimum_raises_target_and_overrides_short_answer_rule(monkeypatch):
    sections = [{"heading": f"{i}. A", "content": " ".join(["isi"] * 300)} for i in range(1, 4)]
    gen, captured = _capture(monkeypatch, sections)
    spec = {"question_count": 3, "answer_type": "jawaban_bernomor", "word_min": 800}
    await gen.generate_academic_draft(QUESTIONS, [], target_words=950, answer_spec=spec)

    system = captured["system"]
    assert "WAJIB paling sedikit 800 kata" in system
    assert "MENGALAHKAN anjuran menjawab singkat" in system
    assert "maksimal 800" not in system
    # Target dinaikkan di atas minimal dan dibagi per butir
    assert "sekitar 960 kata" in system
    assert "rata-rata sekitar" in system
    # Total 900 kata sudah di atas minimal, jadi tidak ada pengembangan
    assert captured["rewrites"] == []


@pytest.mark.anyio
async def test_short_answer_is_expanded_until_minimum(monkeypatch):
    lengths = [97, 122, 117, 106, 87, 76]  # kasus nyata: total 605 untuk minimal 800
    sections = [{"heading": f"{i}. A", "content": " ".join(["isi"] * n)} for i, n in enumerate(lengths, 1)]
    gen, captured = _capture(monkeypatch, sections, grown=180)
    result = await gen.generate_academic_draft(QUESTIONS, [], answer_spec={"question_count": 6, "word_min": 800})

    total = sum(len(s["content"].split()) for s in result["sections"])
    assert total >= 800
    # Bagian terpendek dikembangkan lebih dulu, dan berhenti begitu total cukup
    assert [i for i, _ in captured["rewrites"]] == [5, 4]
    assert "Kembangkan bagian ini" in captured["rewrites"][0][1]


@pytest.mark.anyio
async def test_maximum_asks_for_range_near_the_limit(monkeypatch):
    gen, captured = _capture(monkeypatch, [{"heading": "1. A", "content": "isi"}])
    await gen.generate_academic_draft(QUESTIONS, [], answer_spec={"question_count": 3, "word_limit": 820})
    assert "maksimal 820 kata" in captured["system"]
    assert "antara 738 dan 820 kata" in captured["system"]
    assert captured["rewrites"] == []
