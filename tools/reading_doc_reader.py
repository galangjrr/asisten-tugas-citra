import io
import re
from collections import Counter
from typing import List, Tuple

import pypdf

from tools.question_reader import read_docx_file
from tools.ocr_vision import extract_text_from_pdf

READING_DOC_EXTS = (".pdf", ".docx", ".txt", ".md")
MAX_READING_DOC_BYTES = 20 * 1024 * 1024
# PDF dengan teks sependek ini hampir pasti hasil scan, jadi dibaca lewat OCR Gemini
MIN_PDF_TEXT_CHARS = 50


def _decode_text(file_bytes: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return file_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return file_bytes.decode("utf-8", errors="replace")


def _read_pdf_text(file_bytes: bytes) -> str:
    """Teks per halaman diberi penanda [Halaman n] supaya sitasi hlm. bisa dicek ke berkas asli dosen."""
    reader = pypdf.PdfReader(io.BytesIO(file_bytes))
    pages = [[ln.strip() for ln in (page.extract_text() or "").split("\n")] for page in reader.pages]
    # Kop dan kaki halaman seperti URL situs atau judul buku berulang di tepi hampir tiap halaman.
    # Baris itu bukan isi naskah, jadi dibuang supaya tidak ikut terbaca model atau dikutip.
    # Hanya tepi halaman yang dicek, karena baris berulang di tengah bisa jadi isi seperti judul kolom tabel.
    def edges(lines: list) -> set:
        filled = [ln for ln in lines if ln]
        return set(filled[:2] + filled[-2:])

    counts = Counter(ln for lines in pages for ln in edges(lines))
    repeated = {ln for ln, n in counts.items() if n >= 3 and n >= len(pages) / 2}

    def is_margin(ln: str) -> bool:
        return not ln or ln in repeated or bool(PAGE_NUMBER_LINE.match(ln))

    blocks = []
    for i, lines in enumerate(pages, 1):
        # Baris kosong di tengah tetap disimpan karena jadi pemisah paragraf saat naskah dipotong
        kept = list(lines)
        while kept and is_margin(kept[0]):
            kept.pop(0)
        while kept and is_margin(kept[-1]):
            kept.pop()
        text = "\n".join(kept).strip()
        if text:
            blocks.append(f"[Halaman {i}]\n{text}")
    return "\n\n".join(blocks)


# Nomor halaman cetak yang berdiri sendiri, misal '12' atau '- 12 -' atau 'Halaman 12 dari 30'
PAGE_NUMBER_LINE = re.compile(r"(?i)^(?:-\s*)?(?:hal(?:aman)?\.?\s*|page\s*)?\d{1,4}(?:\s*(?:dari|of|/)\s*\d{1,4})?(?:\s*-)?$")


PAGE_MARKER = re.compile(r"(?m)^\[Halaman (\d+)\]\s*$")


def split_marked_pages(text: str) -> List[Tuple[str, str]]:
    """Memecah teks berpenanda [Halaman n] menjadi (label halaman, isi). Teks tanpa penanda dikembalikan dengan label kosong."""
    parts = PAGE_MARKER.split(text or "")
    pages = [("", parts[0])] if parts[0].strip() else []
    pages += [(f"Halaman {num}", body) for num, body in zip(parts[1::2], parts[2::2]) if body.strip()]
    return pages


async def read_reading_doc(file_bytes: bytes, filename: str) -> Tuple[str, bool]:
    """
    Membaca bahan bacaan dosen secara lokal. Mengembalikan teks dan penanda apakah OCR Gemini dipakai.
    Melempar ValueError untuk format yang tidak didukung atau berkas yang tidak bisa dibuka.
    """
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in READING_DOC_EXTS:
        raise ValueError("Format berkas belum didukung. Pakai PDF, Word .docx, TXT, atau MD.")

    if ext in (".txt", ".md"):
        return _decode_text(file_bytes).strip(), False

    try:
        if ext == ".docx":
            return read_docx_file(file_bytes).strip(), False
        text = _read_pdf_text(file_bytes)
    except Exception as e:
        raise ValueError("Berkas tidak bisa dibuka. Pastikan tidak terkunci kata sandi atau rusak.") from e

    if len(text) >= MIN_PDF_TEXT_CHARS:
        return text, False
    return (await extract_text_from_pdf(file_bytes)).strip(), True
