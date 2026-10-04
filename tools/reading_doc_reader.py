import io
from typing import Tuple

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
    reader = pypdf.PdfReader(io.BytesIO(file_bytes))
    pages = [(page.extract_text() or "").strip() for page in reader.pages]
    return "\n\n".join(p for p in pages if p)


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
