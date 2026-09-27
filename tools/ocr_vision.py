import os
import base64
import asyncio
from google.genai import types
from tools.gemini_client import get_gemini_client


async def extract_text_from_image(image_bytes: bytes, mime_type: str = "image/png") -> str:
    """
    Mengekstrak teks materi dari gambar tangkapan layar modul kuliah.
    Mengabaikan watermark, teks header pembaca, dan menghasilkan teks bersih.
    """
    if not image_bytes or len(image_bytes) < 100:
        return ""

    client = get_gemini_client()
    prompt = (
        "Kamu adalah sistem OCR akademis presisi tinggi. "
        "Tugasmu mengekstrak seluruh teks materi kuliah, paragraf pembahasan, "
        "poin penjelasan, atau daftar bahasan yang ada pada gambar tangkapan layar modul ini. "
        "Abaikan watermark pengguna atau hak cipta kampus seperti 'User: ... HAK CIPTA UT'. "
        "Abaikan tombol navigasi penampil seperti nomor halaman di luar teks materi. "
        "Kembalikan teks materi aslinya secara utuh, rapi, dan mudah dibaca tanpa komentar tambahan."
    )

    candidate_models = [
        "gemini-3.1-flash-lite",
        "gemini-3.6-flash",
        "gemini-3.8-flash"
    ]

    for model_name in candidate_models:
        try:
            response = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model=model_name,
                    contents=[
                        types.Part.from_bytes(
                            data=image_bytes,
                            mime_type=mime_type
                        ),
                        prompt
                    ],
                    config=types.GenerateContentConfig(
                        temperature=0.1
                    )
                ),
                timeout=8.0
            )
            if response.text and response.text.strip():
                return response.text.strip()
        except Exception as e:
            print(f"Vision OCR model {model_name} gagal: {e}")
            continue

    return ""
