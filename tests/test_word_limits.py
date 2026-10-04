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


def _capture(monkeypatch, sections, adjusted_words=None):
    import agents.generator as gen
    captured = {"adjust": []}

    async def fake_generate(category, contents, config=None, **kwargs):
        captured["system"] = config.system_instruction
        return type("Res", (), {"text": json.dumps({"title": "T", "sections": sections})})()

    async def fake_adjust(topic, secs, bounds, **kwargs):
        captured["adjust"].append((sum(len(x["content"].split()) for x in secs), bounds))
        each = adjusted_words // len(secs)
        return [{"heading": x["heading"], "content": " ".join(["kata"] * each)} for x in secs]

    monkeypatch.setattr(gen, "generate_with_fallback", fake_generate)
    monkeypatch.setattr(gen, "adjust_total_length", fake_adjust)
    return gen, captured


def _sections(lengths):
    return [{"heading": f"{i}. A", "content": " ".join(["isi"] * n)} for i, n in enumerate(lengths, 1)]


@pytest.mark.anyio
async def test_minimum_uses_range_and_overrides_short_answer_rule(monkeypatch):
    gen, captured = _capture(monkeypatch, _sections([300, 300, 300]))
    spec = {"question_count": 3, "answer_type": "jawaban_bernomor", "word_min": 800}
    await gen.generate_academic_draft(QUESTIONS, [], target_words=950, answer_spec=spec)

    system = captured["system"]
    assert "WAJIB paling sedikit 800 kata" in system
    assert "Tulis antara 800 dan 1000 kata, target sekitar 880 kata" in system
    assert "MENGALAHKAN anjuran menjawab singkat" in system
    assert "maksimal 800" not in system and "rata-rata sekitar" in system
    # 900 kata sudah di dalam rentang, jadi tidak ada panggilan tambahan
    assert captured["adjust"] == []


@pytest.mark.anyio
async def test_below_minimum_is_adjusted_in_one_call(monkeypatch):
    lengths = [97, 122, 117, 106, 87, 76]  # kasus nyata 605 kata untuk minimal 800
    gen, captured = _capture(monkeypatch, _sections(lengths), adjusted_words=888)
    result = await gen.generate_academic_draft(QUESTIONS, [], answer_spec={"question_count": 6, "word_min": 800})

    assert len(captured["adjust"]) == 1
    total_before, bounds = captured["adjust"][0]
    assert total_before == 605
    assert bounds == {"low": 800, "high": 1000, "goal": 880, "trigger_high": None}
    assert 800 <= sum(len(s["content"].split()) for s in result["sections"]) <= 1000


@pytest.mark.anyio
async def test_above_minimum_without_maximum_is_left_alone(monkeypatch):
    # Kasus nyata 1.181 kata untuk minimal 800: tidak melanggar, dan pemangkasan otomatis terbukti tidak andal
    gen, captured = _capture(monkeypatch, _sections([217, 213, 212, 182, 179, 178]), adjusted_words=888)
    await gen.generate_academic_draft(QUESTIONS, [], answer_spec={"question_count": 6, "word_min": 800})
    assert captured["adjust"] == []


@pytest.mark.anyio
async def test_above_maximum_is_shortened(monkeypatch):
    gen, captured = _capture(monkeypatch, _sections([400, 400, 400]), adjusted_words=780)
    await gen.generate_academic_draft(QUESTIONS, [], answer_spec={"question_count": 3, "word_limit": 820})
    assert len(captured["adjust"]) == 1 and captured["adjust"][0][0] == 1200


@pytest.mark.anyio
async def test_maximum_asks_for_range_near_the_limit(monkeypatch):
    gen, captured = _capture(monkeypatch, _sections([200, 200, 200]))
    await gen.generate_academic_draft(QUESTIONS, [], answer_spec={"question_count": 3, "word_limit": 820})
    assert "maksimal 820 kata" in captured["system"]
    assert "antara 738 dan 820 kata" in captured["system"]
    # Di bawah batas maksimal tidak melanggar aturan dosen, jadi tidak dipanjangkan
    assert captured["adjust"] == []


@pytest.mark.anyio
async def test_adjust_keeps_headings_and_rejects_broken_structure(monkeypatch):
    import agents.generator as gen
    replies = []

    async def fake_generate(category, contents, config=None, **kwargs):
        replies.append(config.system_instruction + contents)
        return type("Res", (), {"text": json.dumps(next(outputs))})()

    monkeypatch.setattr(gen, "generate_with_fallback", fake_generate)
    secs = _sections([300, 300])
    bounds = gen.length_bounds(500, None)

    filler = " ".join(["kata"] * 270)
    outputs = iter([{"sections": [{"heading": "UBAH", "content": f"<p>{filler}</p>"}, {"heading": "UBAH", "content": f'{filler} kutip "x" (A, 2020, hlm. 1).'}]}])
    result = await gen.adjust_total_length("1. A 2. B", secs, bounds)
    assert [s["heading"] for s in result] == ["1. A", "2. A"]
    assert "<p>" not in result[0]["content"] and result[1]["content"].endswith('kutip "x".')
    assert "ubah menjadi sekitar 275 kata" in replies[0]
    assert "Persingkat menjadi sekitar 550 kata" in replies[0]

    outputs = iter([{"sections": [{"heading": "1", "content": "gabungan"}]}])
    with pytest.raises(ValueError):
        await gen.adjust_total_length("1. A 2. B", secs, bounds)

    # Kasus nyata: model cadangan memangkas sampai di bawah minimal, hasilnya harus ditolak
    long_secs = _sections([600, 581])
    outputs = iter([{"sections": [{"heading": "a", "content": " ".join(["k"] * 230)}, {"heading": "b", "content": " ".join(["k"] * 225)}]}])
    with pytest.raises(ValueError, match="di bawah batas minimal"):
        await gen.adjust_total_length("1. A 2. B", long_secs, gen.length_bounds(800, 1000))
    # Model mengabaikan instruksi dan tidak mendekat ke target
    outputs = iter([{"sections": [{"heading": "a", "content": " ".join(["k"] * 200)}, {"heading": "b", "content": " ".join(["k"] * 200)}]}])
    with pytest.raises(ValueError, match="tidak lebih dekat"):
        await gen.adjust_total_length("1. A 2. B", _sections([200, 200]), gen.length_bounds(800, None))
