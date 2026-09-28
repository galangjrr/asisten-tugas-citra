import os
import base64
import asyncio
from google.genai import types
from tools.gemini_client import generate_with_fallback


async def extract_text_from_image(image_bytes: bytes, mime_type: str = "image/png") -> str:
    """
    Mengekstrak teks materi dari gambar tangkapan layar modul kuliah.
    Mengabaikan watermark, teks header pembaca, dan menghasilkan teks bersih.
    """
    if not image_bytes or len(image_bytes) < 100:
        return ""

    prompt = (
        "Kamu adalah sistem OCR akademis presisi tinggi. "
        "Tugasmu mengekstrak seluruh teks materi kuliah, paragraf pembahasan, "
        "poin penjelasan, atau daftar bahasan yang ada pada gambar tangkapan layar modul ini. "
        "Abaikan watermark pengguna atau hak cipta kampus seperti 'User: ... HAK CIPTA UT'. "
        "Abaikan tombol navigasi penampil seperti nomor halaman di luar teks materi. "
        "Kembalikan teks materi aslinya secara utuh, rapi, dan mudah dibaca tanpa komentar tambahan."
    )

    try:
        response = await generate_with_fallback(
            "fast",
            [types.Part.from_bytes(data=image_bytes, mime_type=mime_type), prompt],
            config=types.GenerateContentConfig(temperature=0.1),
            timeout=15.0,
            total_budget=40.0,
        )
    except Exception as e:
        print(f"Vision OCR gagal: {e}")
        return ""

    return response.text.strip()


# Batas data inline Gemini sekitar 20MB per permintaan, disisakan ruang untuk prompt
MAX_PDF_OCR_BYTES = 18 * 1024 * 1024


async def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """
    Mentranskripsi seluruh halaman PDF lembar soal, termasuk halaman hasil scan, lewat pembaca dokumen Gemini.
    Mengembalikan string kosong jika berkas terlalu besar atau semua model gagal.
    """
    if not pdf_bytes or len(pdf_bytes) > MAX_PDF_OCR_BYTES:
        return ""

    prompt = (
        "Transkripsikan SELURUH teks dari semua halaman dokumen lembar tugas kuliah ini, dari halaman pertama sampai terakhir. "
        "Salin kata per kata sesuai urutan baca, jangan meringkas, menerjemahkan, atau memperbaiki isi. "
        "Pertahankan nomor soal, huruf pilihan, label pembicara dialog, dan judul bagian persis seperti di dokumen. "
        "Tulis setiap baris tabel dalam satu baris dengan pemisah ' | '. "
        "Pisahkan paragraf dengan satu baris kosong. Jangan tambahkan komentar, penanda halaman, atau format markdown."
    )

    try:
        response = await generate_with_fallback(
            "fast",
            [types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"), prompt],
            config=types.GenerateContentConfig(temperature=0.0),
            timeout=90.0,
            total_budget=150.0,
        )
    except Exception as e:
        print(f"OCR PDF gagal: {e}")
        return ""

    return response.text.strip()
