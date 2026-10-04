import io
import re
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
    pages = [(i, (page.extract_text() or "").strip()) for i, page in enumerate(reader.pages, 1)]
    return "\n\n".join(f"[Halaman {i}]\n{text}" for i, text in pages if text)


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
