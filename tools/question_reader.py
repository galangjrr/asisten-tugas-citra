import io
import os
import json
import re
import asyncio
from typing import Dict, Any, Optional
import pypdf
import docx
from tools.gemini_client import generate_with_fallback
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


# Judul bagian soal: "Soal:", "Soal 1:", "SOAL TUGAS TUTORIAL I", "Pertanyaan 2.", "Questions".
# Baris metadata seperti "Butir Soal No. : 1 dan 2" sengaja tidak cocok.
QUESTION_HEADING = re.compile(
    r'(?i)^(?:soal|pertanyaan|butir\s+soal|studi\s+kasus|kasus|questions?|tasks?)'
    r'(?:\s+(?:tugas|diskusi|latihan|ujian|tutorial|tuton|uas|uts)(?:\s+[\w.]+){0,3})?'
    r'(?:\s*\d+)?\s*(?::|$|[.)]\s)'
)

# Judul bagian petunjuk, kriteria, rubrik, atau capaian yang jadi catatan dosen.
GUIDELINE_HEADING = re.compile(
    r'(?i)^(?:petunjuk|kriteria|rubrik|ketentuan|tata\s+cara|pedoman|perhatian|catatan|'
    r'capaian\s+pembelajaran|indikator|tujuan|instruksi|instructions?|guidelines?|rubrics?|'
    r'criteria|notes?|remember|purpose|learning\s+outcomes?|format\s+(?:penulisan|jawaban)|'
    r'penilaian|scoring)\b[^:]{0,40}(?::|$)'
)

# Baris skor seperti "Total Score: 100" atau "Bobot 30%".
SCORE_LINE = re.compile(r'(?i)^(?:total\s+)?(?:skor|score|nilai|bobot)\b[^a-z]*\d+\s*%?$')

# Baris metadata kop soal seperti "Program Studi : Sastra Inggris".
META_LINE = re.compile(r'^[^:]{0,40}\s:\s|^:')


def split_questions_and_guidelines(text: str) -> Dict[str, str]:
    """Memilah lembar tugas per bagian: kop dibuang, petunjuk ke guidelines, butir soal ke questions."""
    lines = [ln.strip() for ln in text.split("\n")]
    buckets: Dict[str, list] = {"header": [], "guide": [], "question": []}
    state = "header"
    found_question = False

    for ln in lines:
        if QUESTION_HEADING.match(ln):
            state = "question"
            found_question = True
        elif GUIDELINE_HEADING.match(ln):
            state = "guide"
        elif SCORE_LINE.match(ln):
            buckets["guide"].append(ln)
            continue
        buckets[state].append(ln)

    # Kop halaman yang berulang di tiap halaman PDF ikut terbuang dari soal
    header_lines = {ln for ln in buckets["header"] if ln}
    question_lines = [ln for ln in buckets["question"] if ln not in header_lines]

    # Paragraf panjang di kop, misal narasi studi kasus, tetap dianggap bagian soal
    header_prose = [
        ln for ln in buckets["header"]
        if len(ln) >= 60 and not META_LINE.search(ln)
    ]

    def join(parts: list) -> str:
        return re.sub(r'\n{3,}', "\n\n", "\n".join(parts)).strip()

    questions = join(header_prose + [""] + question_lines)
    guidelines = join([ln for ln in buckets["guide"] if ln not in header_lines])

    # Tanpa judul soal, batas soal dan petunjuk tidak bisa dipastikan, jadi teks dikembalikan utuh
    if not found_question or len(questions) < 20:
        return {"questions": text.strip(), "guidelines": ""}

    return {"questions": questions, "guidelines": guidelines}


ANSWER_TYPES = {"uraian", "terjemahan", "jawaban_singkat", "esai", "makalah", "jawaban_bernomor"}


def count_numbered_questions(topic: str) -> int:
    """Menghitung butir soal bernomor berurutan dari 1, misal '1. Translate...' atau 'Soal 2:'."""
    numbers = {
        int(m.group(1))
        for m in re.finditer(r'(?im)^\s*(?:soal|pertanyaan|question)?\s*(\d{1,2})\s*[.):]\s+\S', topic)
    }
    count = 0
    while count + 1 in numbers:
        count += 1
    return count


def extract_word_limit(text: str) -> Optional[int]:
    """Mencari batas kata seperti '300 words', 'maksimal 500 kata', atau '250-300 kata' (diambil angka terbesar)."""
    match = re.search(r'(?i)\b(\d{2,5})(?:\s*[-–]\s*(\d{2,5}))?\s*(?:kata|words?)\b', text)
    if not match:
        return None
    return int(match.group(2) or match.group(1))


def guess_answer_spec(questions: str, guidelines: str = "") -> Dict[str, Any]:
    """Menebak spesifikasi jawaban dengan pola teks, dipakai saat AI tidak tersedia."""
    combined = f"{questions}\n{guidelines}"
    count = count_numbered_questions(questions)

    if re.search(r'(?i)\btranslat|\bterjemah', questions):
        answer_type = "terjemahan"
    elif re.search(r'(?i)\b(esai|essay)\b', questions):
        answer_type = "esai"
    elif re.search(r'(?i)\bmakalah\b|\bpaper\b|\bbab\s+i\b', questions):
        answer_type = "makalah"
    elif count:
        answer_type = "jawaban_bernomor"
    else:
        answer_type = None

    if answer_type == "terjemahan":
        needs_citations = False
    elif re.search(r'(?i)sitasi|referensi|daftar\s+pustaka|rujukan|kutip|citation|references?\b|cite', combined):
        needs_citations = True
    else:
        needs_citations = None

    language = None
    if re.search(r'(?i)into\s+indonesian|ke\s+(?:dalam\s+)?bahasa\s+indonesia', questions):
        language = "id"
    elif re.search(r'(?i)into\s+english|ke\s+(?:dalam\s+)?bahasa\s+inggris', questions):
        language = "en"

    return {
        "question_count": count or None,
        "answer_type": answer_type,
        "needs_citations": needs_citations,
        "answer_language": language,
        "word_limit": extract_word_limit(combined),
    }


def normalize_answer_spec(raw: Any, questions: str, guidelines: str = "") -> Dict[str, Any]:
    """Merapikan spesifikasi dari AI. Nilai yang tidak valid diganti tebakan pola, bukan dipercaya mentah."""
    guess = guess_answer_spec(questions, guidelines)
    if not isinstance(raw, dict):
        return guess

    def as_int(value: Any, low: int, high: int) -> Optional[int]:
        try:
            number = int(value)
        except (TypeError, ValueError):
            return None
        return number if low <= number <= high else None

    answer_type = raw.get("answer_type")
    language = raw.get("answer_language")
    needs_citations = raw.get("needs_citations")
    return {
        "question_count": as_int(raw.get("question_count"), 1, 50) or guess["question_count"],
        "answer_type": answer_type if answer_type in ANSWER_TYPES else guess["answer_type"],
        "needs_citations": needs_citations if isinstance(needs_citations, bool) else guess["needs_citations"],
        "answer_language": language if language in ("id", "en") else guess["answer_language"],
        "word_limit": as_int(raw.get("word_limit"), 50, 10000) or guess["word_limit"],
    }


async def structure_assignment_with_ai(raw_text: str) -> Optional[Dict[str, Any]]:
    """Memilah lembar tugas secara cerdas menggunakan Gemini."""
    if not os.getenv("GEMINI_API_KEY") or len(raw_text.strip()) < 40:
        return None

    prompt = """Analisis lembar tugas kuliah ini (bisa berbahasa Indonesia atau Inggris).
Tugasmu: Pisahkan struktur dokumen ini ke dalam format JSON yang bersih:
1. "question_topic": HANYA inti pertanyaan tugas, studi kasus, atau instruksi esai yang harus dikerjakan atau dijawab. BUANG kop dokumen (fakultas, prodi, kode mata kuliah, tahun, skor maks), capaian pembelajaran, indikator, label judul seperti "Guidelines:", "Petunjuk:", "Rubrik:", "Remember!", "Purpose:", batas waktu atau sesi, dan kalimat sapaan. Salin butir soal beserta teks kasus, dialog, atau bacaan pendukungnya PERSIS kata per kata, jangan diringkas atau diterjemahkan.
2. "guidelines": Seluruh capaian pembelajaran, indikator, petunjuk teknis, rubrik penilaian, kriteria dosen, ketentuan format, atau batasan kata yang harus dipatuhi saat menulis jawaban.
3. "course_code": Kode mata kuliah resmi jika ada (contoh: EKMA4116, FSSI4206), atau null.
4. "answer_spec": spesifikasi bentuk jawaban yang diminta dosen:
   - "question_count": jumlah butir soal utama yang harus dijawab, atau null jika berupa satu topik esai tanpa nomor.
   - "answer_type": salah satu dari "terjemahan" (menerjemahkan teks), "jawaban_singkat" (isian, hitungan, atau jawaban pendek), "esai" (satu esai mengalir), "makalah" (makalah berbab), "jawaban_bernomor" (uraian per nomor soal), atau "uraian" (uraian analitis umum).
   - "needs_citations": true jika dosen meminta sitasi, referensi, atau daftar pustaka; false jika tugas jelas tidak butuh rujukan seperti terjemahan atau hitungan; null jika tidak jelas.
   - "answer_language": "id" atau "en", yaitu bahasa yang harus dipakai untuk MENULIS JAWABAN. Untuk soal terjemahan, ini bahasa sasaran terjemahan, bukan bahasa teks soal. null jika tidak jelas.
   - "word_limit": angka batas kata jika disebutkan (jika rentang seperti 250-300 kata, isi angka terbesar), atau null.

Format Keluaran (JSON murni):
{
  "question_topic": "...",
  "guidelines": "...",
  "course_code": null,
  "answer_spec": {
    "question_count": null,
    "answer_type": "uraian",
    "needs_citations": null,
    "answer_language": null,
    "word_limit": null
  }
}

Dokumen Tugas:
""" + raw_text[:12000]

    try:
        res = await generate_with_fallback(
            "fast",
            prompt,
            config={"response_mime_type": "application/json"},
            timeout=15.0,
            total_budget=40.0,
        )
        parsed = json.loads(res.text)
    except Exception as e:
        print(f"Peringatan: pemilah AI lembar tugas gagal, beralih ke pemilah pola: {e}")
        return None

    if isinstance(parsed, list) and parsed:
        parsed = parsed[0]
    if not isinstance(parsed, dict):
        return None

    # Jika guidelines berupa list, jadikan teks per baris
    g = parsed.get("guidelines")
    if isinstance(g, list):
        parsed["guidelines"] = "\n".join(str(item) for item in g)

    return parsed


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
        questions = q_topic if len(q_topic) >= 10 else clean_text
        g_lines = str(ai_res.get("guidelines", "")).strip()
        c_code = ai_res.get("course_code") or detected_code
        spec = normalize_answer_spec(ai_res.get("answer_spec"), questions, g_lines)

        return {
            "success": True,
            "filename": filename,
            "file_type": file_type,
            "text": clean_text,
            "questions": questions,
            "detected_guidelines": g_lines,
            "char_count": len(clean_text),
            "detected_course_code": c_code,
            "word_count_hint": spec["word_limit"],
            "answer_spec": spec,
            "answer_spec_source": "ai",
        }

    # Fallback ke pemisah pola aturan regex jika AI tidak tersedia
    split_res = split_questions_and_guidelines(clean_text)
    questions = split_res.get("questions", clean_text)
    guidelines = split_res.get("guidelines", "")
    spec = guess_answer_spec(questions, guidelines)

    return {
        "success": bool(clean_text),
        "filename": filename,
        "file_type": file_type,
        "text": clean_text,
        "questions": questions,
        "detected_guidelines": guidelines,
        "char_count": len(clean_text),
        "detected_course_code": detected_code,
        "word_count_hint": spec["word_limit"],
        "answer_spec": spec,
        "answer_spec_source": "pola",
    }

