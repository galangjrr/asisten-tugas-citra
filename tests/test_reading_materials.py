import io

import docx
from fastapi.testclient import TestClient

from api.main import app
from api.routes import CACHED_PAPERS
from tools.content_chunker import chunk_paragraphs

client = TestClient(app)


def test_chunker_keeps_paragraphs_and_respects_limit():
    text = "\n\n".join(f"Paragraf {i}. " + "kata " * 150 for i in range(10))
    chunks = chunk_paragraphs(text, max_chars=1000)
    assert len(chunks) > 1
    assert all(len(c) <= 1000 for c in chunks)
    assert chunks[0].startswith("Paragraf 0.")


def test_chunker_splits_giant_paragraph_at_sentence():
    text = "Kalimat panjang sekali. " * 300
    chunks = chunk_paragraphs(text, max_chars=500)
    assert all(len(c) <= 500 for c in chunks)
    assert all(c.endswith(".") for c in chunks[:-1])


def test_parse_reading_doc_txt_and_docx():
    res = client.post("/api/parse-reading-doc", files={"file": ("cerpen.txt", "Robohnya Surau Kami bercerita tentang kakek.".encode(), "text/plain")})
    data = res.json()
    assert data["success"] and data["char_count"] == len(data["text"])

    d = docx.Document()
    d.add_paragraph("Bab satu membahas kemiskinan struktural di desa.")
    buf = io.BytesIO()
    d.save(buf)
    res = client.post("/api/parse-reading-doc", files={"file": ("bab1.docx", buf.getvalue())})
    assert "kemiskinan struktural" in res.json()["text"]


def test_parse_reading_doc_rejects_unknown_format():
    res = client.post("/api/parse-reading-doc", files={"file": ("gambar.png", b"0" * 50)})
    assert res.status_code == 400


def test_manual_module_non_ut_has_no_ut_label():
    res = client.post("/api/manual-module", json={
        "module_title": "Robohnya Surau Kami",
        "author": "A.A. Navis",
        "year": 1956,
        "content_text": "Kalau beberapa tahun yang lalu Tuan datang ke kota kelahiranku.\n\n" * 80,
    })
    data = res.json()
    assert res.status_code == 200
    assert data["is_ut_bmp"] is False
    assert "Universitas Terbuka" not in (data["venue"] or "")
    cached = CACHED_PAPERS[data["id"]]
    assert len(cached["pages_content"]) > 1
    assert cached["pages_content"][0]["page_number"] == "Bagian 1"


def test_manual_module_ut_code_gets_ut_label():
    res = client.post("/api/manual-module", json={"module_title": "MKWU4108", "content_text": "Materi bahasa Indonesia ragam ilmiah."})
    data = res.json()
    assert data["is_ut_bmp"] is True
    assert data["authors"] == ["Universitas Terbuka"]


def test_pdf_reader_drops_repeated_header_footer_and_page_numbers():
    import anyio
    from reportlab.pdfgen import canvas
    from tools.reading_doc_reader import read_reading_doc

    buf = io.BytesIO()
    pdf = canvas.Canvas(buf)
    for page in range(1, 5):
        pdf.drawString(72, 800, "https://americanliterature.com/author/willa-cather/short-story")
        pdf.drawString(72, 700, f"Isi cerita halaman {page} tentang kakek penjaga surau dan Ajo Sidi.")
        pdf.drawString(72, 650, "1896")
        pdf.drawString(72, 600, f"Isi lanjutan halaman {page} yang tetap harus terbaca utuh.")
        pdf.drawString(300, 40, str(page))
        pdf.showPage()
    pdf.save()

    text, _ = anyio.run(read_reading_doc, buf.getvalue(), "cerpen.pdf")
    assert "americanliterature.com" not in text
    assert "[Halaman 4]" in text and "Isi cerita halaman 4" in text
    # Nomor halaman di kaki halaman dibuang, angka di tengah naskah tetap
    assert "\n4\n" not in text + "\n" and not text.rstrip().endswith("\n4")
    assert "1896" in text and "Isi lanjutan halaman 4" in text
