import io
import os
import json
import re
import asyncio
from typing import Dict, Any, Optional
import pypdf
import docx
from tools.gemini_client import get_gemini_client, get_active_models
from tools.ocr_vision import extract_text_from_image


def extract_course_code_from_text(text: str) -> Optional[str]:
    """Mencari pola kode mata kuliah UT seperti EKMA4116 atau FSSI 4206 di lembar soal."""
    match = re.search(r'\b([A-Za-z]{4})\s*(\d{4})\b', text)
    if match:
        return f"{match.group(1).upper()}{match.group(2)}"
    return None


def read_docx_file(file_bytes: bytes) -> str:
    """Membaca seluruh teks dan tabel dari berkas dokumen Microsoft Word docx."""
    doc = docx.Document(io.BytesIO(file_bytes))
    paragraphs = []
    
    for p in doc.paragraphs:
        t = p.text.strip()
        if t:
            paragraphs.append(t)

    # Baca juga teks di dalam tabel jika dosen membuat soal bertabel
    for table in doc.tables:
        for row in table.rows:
            row_texts = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if row_texts:
                paragraphs.append(" | ".join(dict.fromkeys(row_texts)))

    return "\n\n".join(paragraphs)


async def read_pdf_file(file_bytes: bytes) -> str:
    """Membaca teks dari berkas PDF lembar tugas, dengan fallback vision OCR jika hasil scan."""
    reader = pypdf.PdfReader(io.BytesIO(file_bytes))
    page_texts = []

    for page in reader.pages:
        t = page.extract_text() or ""
        if t.strip():
            page_texts.append(t.strip())

    extracted = "\n\n".join(page_texts)

    # Jika teks hasil ekstraksi pypdf kosong atau terlalu pendek (indikasi PDF scan gambar)
    if len(extracted.strip()) < 50 and len(reader.pages) > 0:
        # Gunakan fallback ke Gemini Vision OCR untuk halaman pertama
        try:
            # Cari gambar di halaman pertama jika ada
            first_page = reader.pages[0]
            if len(first_page.images) > 0:
                first_img = first_page.images[0]
                ocr_result = await extract_text_from_image(first_img.data, mime_type="image/png")
                if ocr_result:
                    return ocr_result
        except Exception:
            pass

    return extracted


def split_questions_and_guidelines(text: str) -> Dict[str, str]:
    """Memisahkan petunjuk teknis atau kriteria penilaian dari butir soal inti jika terdeteksi."""
    soal_match = re.search(
        r'(?i)(?:^|\n+)\s*(?:soal\s*(?:tugas|diskusi|latihan|ujian)?\s*[:\d\-]|pertanyaan\s*[:\d\-]|kasus\s*[:\d\-]|butir\s*soal|\bsoal\s*1\b|\bpertanyaan\s*1\b|\bsoal\s*:|\bpertanyaan\s*:|\bkasus\s*:)',
        text
    )

    if soal_match:
        split_idx = soal_match.start()
        header_part = text[:split_idx].strip()
        soal_part = text[split_idx:].strip()

        # Periksa apakah bagian atas memuat petunjuk atau kriteria penilaian
        has_guidelines = re.search(
            r'(?i)(?:petunjuk|kriteria|rubrik|ketentuan|tata\s*cara|format|pedoman|perhatian|bobot)',
            header_part
        )
        if has_guidelines and len(soal_part) >= 20:
            return {
                "questions": soal_part,
                "guidelines": header_part
            }

    return {
        "questions": text.strip(),
        "guidelines": ""
    }


async def structure_assignment_with_ai(raw_text: str) -> Optional[Dict[str, Any]]:
    """Memilah lembar tugas secara cerdas menggunakan Gemini."""
    if not os.getenv("GEMINI_API_KEY") or len(raw_text.strip()) < 40:
        return None

    prompt = """Analisis lembar tugas kuliah ini (bisa berbahasa Indonesia atau Inggris).
Tugasmu: Pisahkan struktur dokumen ini ke dalam format JSON yang bersih:
1. "question_topic": HANYA inti pertanyaan tugas, studi kasus, atau instruksi esai yang harus dikerjakan atau dijawab. BUANG label judul seperti "Guidelines:", "Petunjuk:", "Rubrik:", "Remember!", "Purpose:", batas waktu atau sesi, dan kalimat sapaan. Pertahankan esensi tugas secara utuh dan jelas.
2. "guidelines": Seluruh petunjuk teknis, rubrik penilaian, kriteria dosen, ketentuan format, atau batasan kata yang harus dipatuhi saat menulis jawaban.
3. "course_code": Kode mata kuliah resmi jika ada (contoh: EKMA4116, FSSI4206), atau null.
4. "word_count_hint": Angka batas kata jika disebutkan (contoh: jika tertulis '300 words' isi 300), atau null jika tidak disebutkan.

Format Keluaran (JSON murni):
{
  "question_topic": "...",
  "guidelines": "...",
  "course_code": null,
  "word_count_hint": null
}

Dokumen Tugas:
""" + raw_text[:3500]

    try:
        client = get_gemini_client()
    except Exception:
        return None

    candidate_models = await get_active_models("fast")

    for model_name in candidate_models:
        try:
            res = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config={"response_mime_type": "application/json"}
                ),
                timeout=4.0
            )
            if res.text:
                parsed = json.loads(res.text)
                if isinstance(parsed, list) and len(parsed) > 0:
                    parsed = parsed[0]

                # Jika guidelines berupa list, jadikan teks per baris
                g = parsed.get("guidelines")
                if isinstance(g, list):
                    parsed["guidelines"] = "\n".join(str(item) for item in g)

                return parsed
        except Exception as e:
            print(f"Peringatan: Model {model_name} gagal memilah lembar tugas: {e}")
            continue

    return None


async def parse_question_document(file_bytes: bytes, filename: str) -> Dict[str, Any]:
    """Membaca berkas soal dosen (PDF, DOCX, TXT) secara utuh tanpa memotong isi."""
    fn_lower = filename.lower()
    text = ""
    file_type = "unknown"

    if fn_lower.endswith(".docx"):
        file_type = "docx"
        text = read_docx_file(file_bytes)
    elif fn_lower.endswith(".pdf"):
        file_type = "pdf"
        text = await read_pdf_file(file_bytes)
    elif fn_lower.endswith(".txt"):
        file_type = "txt"
        text = file_bytes.decode("utf-8", errors="replace").strip()
    else:
        # Coba baca sebagai docx, jika gagal coba pdf
        try:
            text = read_docx_file(file_bytes)
            file_type = "docx"
        except Exception:
            text = await read_pdf_file(file_bytes)
            file_type = "pdf"

    clean_text = text.strip()
    detected_code = extract_course_code_from_text(clean_text)

    # Coba gunakan pemilah cerdas AI terlebih dahulu
    ai_res = await structure_assignment_with_ai(clean_text)
    if ai_res and ai_res.get("question_topic"):
        q_topic = str(ai_res.get("question_topic", "")).strip()
        g_lines = str(ai_res.get("guidelines", "")).strip()
        c_code = ai_res.get("course_code") or detected_code
        w_hint = ai_res.get("word_count_hint")

        return {
            "success": True,
            "filename": filename,
            "file_type": file_type,
            "text": clean_text,
            "questions": q_topic if len(q_topic) >= 10 else clean_text,
            "detected_guidelines": g_lines,
            "char_count": len(clean_text),
            "detected_course_code": c_code,
            "word_count_hint": w_hint
        }

    # Fallback ke pemisah pola aturan regex jika AI tidak tersedia
    split_res = split_questions_and_guidelines(clean_text)

    return {
        "success": bool(clean_text),
        "filename": filename,
        "file_type": file_type,
        "text": clean_text,
        "questions": split_res.get("questions", clean_text),
        "detected_guidelines": split_res.get("guidelines", ""),
        "char_count": len(clean_text),
        "detected_course_code": detected_code,
        "word_count_hint": None
    }

