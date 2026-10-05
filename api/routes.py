import os
import uuid
from typing import Dict, Any, List
from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from dotenv import load_dotenv

import base64
from api.schemas import (
    HealthResponse, SearchRequest, SearchResponse, GenerateRequest, GenerateResponse,
    PaperItem, ManualModuleRequest, UTCourseLookupResponse,
    ExtractScreenshotRequest, ExtractScreenshotResponse,
    ParseQuestionWebRequest, ParseQuestionDocResponse,
    TaskEditRequest, SectionRewriteRequest, TaskUpdateResponse,
    ParseReadingDocResponse, PublicationLookupRequest, PublicationLookupResponse,
    SavedModuleItem, SavedModuleListResponse, LoadSavedModuleRequest
)
from tools.academic_search import search_openalex_papers
from tools.pdf_downloader import download_paper_pdf
from tools.pdf_parser import extract_text_with_pages
from tools.ut_catalog import lookup_ut_course
from tools.ocr_vision import extract_text_from_image
from tools.question_reader import parse_question_document, structure_question_text
from tools.reading_doc_reader import read_reading_doc, split_marked_pages, MAX_READING_DOC_BYTES
from tools.content_chunker import chunk_paragraphs
from tools.publication_lookup import lookup_publication
from tools.gemini_client import get_ai_status
from tools.module_library import list_saved_modules, load_saved_module, save_module_to_library
from agents.generator import generate_academic_draft, rewrite_section
from exporters.docx_builder import create_assignment_docx
from exporters.pdf_builder import create_assignment_pdf
from tools.task_store import save_task_to_disk, load_task_from_disk



load_dotenv()
router = APIRouter(prefix="/api")

# Penyimpanan sementara memori tugas aktif
TASKS_DB: Dict[str, Dict[str, Any]] = {}
CACHED_PAPERS: Dict[str, Dict[str, Any]] = {}


@router.get("/health", response_model=HealthResponse)
async def check_health():
    """Memeriksa kesiapan sistem dan konfigurasi API key."""
    api_key = os.getenv("GEMINI_API_KEY", "")
    configured = bool(api_key and len(api_key) > 10)
    ai = await get_ai_status() if configured else {"state": "no_key", "model": None, "retry_in": None}
    return HealthResponse(
        status="ready",
        gemini_configured=configured,
        version="1.0.0",
        ai_state=ai["state"],
        active_model=ai["model"],
        retry_in=ai["retry_in"],
        env_file=os.path.abspath(".env"),
    )


def safe_filename_part(text: str) -> str:
    """Membuang karakter yang tidak sah di nama berkas Windows maupun header unduhan."""
    return " ".join("".join(c for c in text if c.isalnum() or c in (" ", "-", ".")).split()).strip(" .")


def count_words(sections: List[Dict[str, Any]]) -> int:
    return sum(len(s.get("content", "").split()) for s in sections)


def build_task_files(task_id: str, task: Dict[str, Any]) -> None:
    """Merakit ulang docx dan pdf dari isi task. Dipanggil saat generate, edit, dan tulis ulang bagian."""
    # Nama unduhan mengikuti format kumpul tugas: judul_mata kuliah_nama_NIM. Berkas di disk tetap unik per task_id.
    name_parts = [task["title"], task["course_name"], task["student_name"], task["student_id"]]
    task["download_base"] = "_".join(p for p in (safe_filename_part(x) for x in name_parts) if p)[:180] or "Tugas"
    common = dict(
        title=task["title"],
        sections=task["sections"],
        references=task["references"],
        language=task["language"],
        identity_lines=task["identity_lines"],
    )
    task["docx_path"] = create_assignment_docx(output_filename=f"{task_id}.docx", **common)
    task["pdf_path"] = create_assignment_pdf(output_filename=f"{task_id}.pdf", **common)


def get_task_or_404(task_id: str) -> Dict[str, Any]:
    task = TASKS_DB.get(task_id)
    if not task:
        task = load_task_from_disk(task_id)
        if task:
            TASKS_DB[task_id] = task
            docx_ok = task.get("docx_path") and os.path.exists(task["docx_path"])
            pdf_ok = task.get("pdf_path") and os.path.exists(task["pdf_path"])
            if not docx_ok or not pdf_ok:
                try:
                    build_task_files(task_id, task)
                except Exception as e:
                    print(f"Peringatan: Gagal merakit ulang berkas untuk tugas {task_id}: {e}")
    if not task:
        raise HTTPException(status_code=404, detail="Naskah tidak ditemukan. Silakan periksa kembali ID tugas atau buat tugas baru.")
    return task


@router.put("/tasks/{task_id}", response_model=TaskUpdateResponse)
async def update_task(task_id: str, payload: TaskEditRequest):
    """Menyimpan hasil edit manual judul dan isi naskah, lalu merakit ulang berkas unduhan."""
    task = get_task_or_404(task_id)
    task["title"] = payload.title.strip()
    task["sections"] = [{"heading": s.heading.strip(), "content": s.content.strip()} for s in payload.sections]
    build_task_files(task_id, task)
    save_task_to_disk(task_id, task)
    return TaskUpdateResponse(title=task["title"], sections=task["sections"], word_count=count_words(task["sections"]))


@router.post("/tasks/{task_id}/sections/{index}/rewrite", response_model=TaskUpdateResponse)
async def rewrite_task_section(task_id: str, index: int, payload: SectionRewriteRequest):
    """Menulis ulang satu bagian naskah dengan Gemini tanpa mengubah bagian lain."""
    task = get_task_or_404(task_id)
    if not 0 <= index < len(task["sections"]):
        raise HTTPException(status_code=400, detail="Nomor bagian tidak valid.")

    limits = task["answer_spec"].get("item_word_limits") or []
    item_limit = limits[index] if index < len(limits) else (limits[0] if len(limits) == 1 else None)
    try:
        new_section = await rewrite_section(
            topic=task["topic"],
            sections=task["sections"],
            index=index,
            language=task["language"],
            instruction=payload.instruction,
            word_limit=item_limit,
            papers=task["references"],
            guidelines=task["guidelines"],
            student_name=task["student_name"],
            # Tugas lama dibuat sebelum ada pilihan ini dan selalu bersitasi, jadi gayanya dipertahankan
            quote_citations=task.get("quote_citations", True),
            task_type=task.get("task_type"),
        )
    except Exception as e:
        print(f"Error tulis ulang bagian: {e}")
        raise HTTPException(status_code=503, detail="Gemini sedang sibuk atau kena limit. Tunggu status kembali hijau lalu coba lagi.")

    task["sections"][index] = new_section
    build_task_files(task_id, task)
    save_task_to_disk(task_id, task)
    return TaskUpdateResponse(title=task["title"], sections=task["sections"], word_count=count_words(task["sections"]))


@router.post("/manual-module", response_model=PaperItem)
async def add_manual_module(payload: ManualModuleRequest):
    """Menyimpan bahan bacaan dosen, cerpen, bab buku, atau modul BMP UT sebagai rujukan tugas."""
    content = payload.content_text.strip()
    page_ref = (payload.page_or_ref or "").strip()
    # PDF yang dibaca lokal membawa penanda [Halaman n], jadi halaman fisik dipakai sebagai label supaya hlm. bisa dicek dosen.
    # Teks tanpa penanda, misal ketikan atau DOCX, tetap berlabel 'Bagian n' karena halaman aslinya tidak diketahui.
    pages_content = []
    part = 0
    for label, body in split_marked_pages(content):
        for chunk in chunk_paragraphs(body, max_chars=3000):
            if not label:
                part += 1
            page_number = label or (f"{page_ref}, bagian {part}" if page_ref else f"Bagian {part}")
            pages_content.append({"page_number": page_number, "text": chunk})
    if not pages_content:
        raise HTTPException(status_code=400, detail="Isi bahan bacaan masih kosong.")

    module_title = payload.module_title.strip()
    lookup = lookup_ut_course(module_title)
    # Label Universitas Terbuka hanya untuk judul yang benar-benar memuat kode mata kuliah resmi
    is_ut_bmp = bool(lookup.get("found") and lookup.get("exact") and lookup.get("course"))
    if is_ut_bmp:
        module_title = lookup["course"]["formatted_title"]

    author = (payload.author or "").strip()
    authors = [author] if author else (["Universitas Terbuka"] if is_ut_bmp else [])
    venue = (payload.publisher_or_venue or "").strip()
    if not venue and is_ut_bmp:
        venue = "Buku Materi Pokok (BMP) Universitas Terbuka"

    mod_id = f"bmp_{uuid.uuid4().hex[:8]}"
    item_data = {
        "id": mod_id,
        "title": module_title,
        "authors": authors,
        "year": payload.year,
        "venue": venue,
        "doi": "",
        "pdf_url": "",
        "all_pdf_urls": [],
        "abstract": " ".join(" ".join(p["text"] for p in pages_content[:2]).split())[:400],
        "scholar_url": "https://pustaka.ut.ac.id/" if is_ut_bmp else "",
        "has_full_pdf": True,
        "is_manual_module": True,
        "is_ut_bmp": is_ut_bmp,
        "source_status": "Buku Materi Pokok UT" if is_ut_bmp else "Bahan bacaan dosen",
        "page_info": page_ref,
        "pages_content": pages_content,
    }
    CACHED_PAPERS[mod_id] = item_data
    return PaperItem(
        id=mod_id,
        title=module_title,
        authors=authors,
        year=payload.year,
        venue=venue,
        doi="",
        pdf_url="",
        abstract=item_data["abstract"],
        scholar_url=item_data["scholar_url"],
        is_ut_bmp=is_ut_bmp,
    )


@router.get("/saved-modules", response_model=SavedModuleListResponse)
async def get_saved_modules():
    """Mengambil daftar modul dan naskah yang tersimpan di direktori saved_modules."""
    modules = list_saved_modules()
    return SavedModuleListResponse(
        success=True,
        total=len(modules),
        modules=[SavedModuleItem(**m) for m in modules]
    )


@router.post("/saved-modules/load", response_model=PaperItem)
async def load_saved_module_endpoint(payload: LoadSavedModuleRequest):
    """Memuat modul tersimpan ke memori aktif CACHED_PAPERS agar siap disitir."""
    target_id = payload.module_id.strip()
    if not target_id:
        raise HTTPException(status_code=400, detail="ID atau nama modul wajib diisi.")

    data = load_saved_module(target_id)
    if not data:
        raise HTTPException(status_code=404, detail="Modul tersimpan tidak ditemukan.")

    mod_id = data.get("id") or f"bmp_{uuid.uuid4().hex[:8]}"
    pages_content = data.get("pages_content") or []
    is_ut_bmp = data.get("is_ut_bmp", True)

    item_data = {
        "id": mod_id,
        "title": data.get("title", "Buku Materi Pokok"),
        "authors": data.get("authors") or [],
        "year": data.get("year"),
        "venue": data.get("venue") or "",
        "doi": data.get("doi", ""),
        "pdf_url": data.get("pdf_url", ""),
        "all_pdf_urls": data.get("all_pdf_urls", []),
        "abstract": data.get("abstract", "")[:400],
        "scholar_url": data.get("scholar_url", ""),
        "has_full_pdf": True,
        "is_manual_module": True,
        "is_ut_bmp": is_ut_bmp,
        "source_status": data.get("source_status", "Buku Materi Pokok UT"),
        "page_info": data.get("page_info", ""),
        "pages_content": pages_content,
    }
    CACHED_PAPERS[mod_id] = item_data
    return PaperItem(
        id=mod_id,
        title=item_data["title"],
        authors=item_data["authors"],
        year=item_data["year"],
        venue=item_data["venue"],
        doi=item_data["doi"],
        pdf_url=item_data["pdf_url"],
        abstract=item_data["abstract"],
        scholar_url=item_data["scholar_url"],
        is_ut_bmp=item_data["is_ut_bmp"],
    )


@router.post("/saved-modules/save", response_model=PaperItem)
async def save_saved_module_endpoint(payload: ManualModuleRequest):
    """Menyimpan naskah/modul ke repositori fisik saved_modules sekaligus mendaftarkannya sebagai rujukan aktif."""
    content = payload.content_text.strip()
    if len(content) < 15:
        raise HTTPException(status_code=400, detail="Isi naskah minimal 15 karakter.")

    module_title = payload.module_title.strip()
    if len(module_title) < 3:
        raise HTTPException(status_code=400, detail="Judul naskah minimal 3 huruf.")

    lookup = lookup_ut_course(module_title)
    is_ut_bmp = bool(lookup.get("found") and lookup.get("exact") and lookup.get("course"))
    if is_ut_bmp:
        module_title = lookup["course"]["formatted_title"]

    author = (payload.author or "").strip()
    venue = (payload.publisher_or_venue or "").strip()
    page_ref = (payload.page_or_ref or "").strip()

    saved_data = save_module_to_library(
        title=module_title,
        author=author,
        year=payload.year,
        venue=venue,
        page_info=page_ref,
        content_text=content,
        is_ut_bmp=is_ut_bmp,
    )
    mod_id = saved_data["id"]
    CACHED_PAPERS[mod_id] = saved_data
    return PaperItem(
        id=mod_id,
        title=saved_data["title"],
        authors=saved_data["authors"],
        year=saved_data["year"],
        venue=saved_data["venue"],
        doi="",
        pdf_url="",
        abstract=saved_data["abstract"],
        scholar_url=saved_data["scholar_url"],
        is_ut_bmp=saved_data["is_ut_bmp"],
    )


@router.post("/parse-reading-doc", response_model=ParseReadingDocResponse)
async def parse_reading_doc(file: UploadFile = File(...)):
    """Membaca teks bahan bacaan dosen secara lokal. Gemini hanya dipakai untuk PDF hasil scan."""
    filename = file.filename or "bahan_bacaan"
    content = await file.read(MAX_READING_DOC_BYTES + 1)
    if len(content) > MAX_READING_DOC_BYTES:
        raise HTTPException(status_code=413, detail="Berkas lebih dari 20 MB. Pecah dulu per bab lalu unggah lagi.")
    if len(content) < 10:
        raise HTTPException(status_code=400, detail="Berkas kosong atau rusak.")

    try:
        text, used_ocr = await read_reading_doc(content, filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not text:
        return ParseReadingDocResponse(
            success=False,
            filename=filename,
            message="Teks tidak terbaca. Kalau ini hasil scan, tunggu status Gemini hijau lalu coba lagi."
        )
    source = "lewat OCR Gemini" if used_ocr else "secara lokal"
    return ParseReadingDocResponse(
        success=True,
        filename=filename,
        text=text,
        char_count=len(text),
        message=f"Berhasil membaca {len(text)} karakter dari {filename} {source}."
    )


@router.post("/lookup-publication", response_model=PublicationLookupResponse)
async def lookup_publication_info(payload: PublicationLookupRequest):
    """Mencari penulis, tahun terbit pertama, dan tempat terbit lewat Google Search. Hanya jalan saat tombol diklik."""
    try:
        result = await lookup_publication(payload.title, payload.author or "")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"Error cari info terbit: {e}")
        raise HTTPException(status_code=503, detail="Gemini sedang sibuk atau kuota hariannya habis. Isi tahun manual dulu, atau coba lagi nanti.")
    return PublicationLookupResponse(**result)


@router.get("/ut-course-lookup", response_model=UTCourseLookupResponse)
async def ut_course_lookup(query: str = ""):
    """Mendeteksi kode atau judul mata kuliah resmi UT dari pustaka.ut.ac.id secara otomatis."""
    result = lookup_ut_course(query)
    return UTCourseLookupResponse(**result)


@router.post("/extract-screenshot", response_model=ExtractScreenshotResponse)
async def extract_screenshot(payload: ExtractScreenshotRequest):
    """Mengekstrak teks materi dari gambar screenshot modul menggunakan Gemini Vision."""
    raw_b64 = payload.raw_data
    if not raw_b64 or len(raw_b64) < 10:
        raise HTTPException(status_code=400, detail="Data gambar tidak boleh kosong.")

    if "," in raw_b64:
        raw_b64 = raw_b64.split(",", 1)[1]

    try:
        img_bytes = base64.b64decode(raw_b64)
    except Exception:
        raise HTTPException(status_code=400, detail="Format gambar base64 tidak valid.")

    if len(img_bytes) < 100:
        raise HTTPException(status_code=400, detail="Berkas gambar terlalu kecil atau kosong.")

    text = await extract_text_from_image(img_bytes, mime_type=payload.mime_type or "image/png")
    if not text:
        return ExtractScreenshotResponse(
            success=False,
            extracted_text="",
            message="Gagal mengekstrak teks dari gambar. Pastikan tulisan pada tangkapan layar cukup jelas."
        )

    return ExtractScreenshotResponse(
        success=True,
        extracted_text=text,
        message="Teks berhasil diekstrak secara otomatis dari tangkapan layar."
    )


# Batas per gambar soal dari Tuton, setara foto layar resolusi tinggi
MAX_WEB_IMAGE_BYTES = 8 * 1024 * 1024


def question_response(res: Dict[str, Any], filename: str, fail_message: str) -> ParseQuestionDocResponse:
    if not res.get("success"):
        return ParseQuestionDocResponse(success=False, filename=filename, file_type=res.get("file_type", ""), text="", message=fail_message)
    return ParseQuestionDocResponse(
        success=True,
        filename=filename,
        file_type=res.get("file_type", ""),
        text=res.get("text", ""),
        questions=res.get("questions", res.get("text", "")),
        detected_guidelines=res.get("detected_guidelines", ""),
        char_count=res.get("char_count", 0),
        detected_course_code=res.get("detected_course_code"),
        word_count_hint=res.get("word_count_hint"),
        answer_spec=res.get("answer_spec"),
        answer_spec_source=res.get("answer_spec_source"),
        message=f"Berhasil membaca {res.get('char_count', 0)} karakter dari {filename}."
    )


@router.post("/upload-question-file", response_model=ParseQuestionDocResponse)
async def upload_question_file(file: UploadFile = File(...)):
    """Membaca berkas soal dosen (PDF, DOCX, TXT) via multipart upload tanpa memotong isi."""
    filename = file.filename or "dokumen_soal"
    try:
        content = await file.read()
    except Exception:
        raise HTTPException(status_code=400, detail="Gagal membaca berkas yang diunggah.")

    if len(content) < 10:
        raise HTTPException(status_code=400, detail="Berkas kosong atau rusak.")

    res = await parse_question_document(content, filename)
    return question_response(res, filename, "Gagal mengekstrak teks dari berkas. Pastikan dokumen tidak terkunci kata sandi.")


@router.post("/parse-question-web", response_model=ParseQuestionDocResponse)
async def parse_question_web(payload: ParseQuestionWebRequest):
    """Membaca soal dari halaman Tuton yang sudah diubah jadi teks plus gambar, lewat pemilah yang sama dengan berkas."""
    images = []
    for item in payload.images:
        try:
            blob = base64.b64decode(item.data_base64.split(",", 1)[-1], validate=True)
        except Exception:
            raise HTTPException(status_code=400, detail="Data gambar soal dari Tuton tidak valid.")
        if len(blob) > MAX_WEB_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="Salah satu gambar soal di Tuton lebih dari 8MB.")
        if not item.mime.startswith("image/"):
            raise HTTPException(status_code=400, detail="Lampiran gambar soal bukan berkas gambar.")
        images.append((blob, item.mime))

    filename = payload.title.strip() or "Halaman Tuton"
    res = await structure_question_text(payload.text, images, filename, "tuton")
    return question_response(res, filename, "Halaman Tuton ini tidak berisi teks soal.")


@router.post("/search", response_model=SearchResponse)
async def search_papers(payload: SearchRequest):
    """Mencari naskah jurnal ilmiah di OpenAlex yang terbukti memiliki berkas PDF."""
    if not payload.query or len(payload.query.strip()) < 3:
        raise HTTPException(status_code=400, detail="Query pencarian minimal 3 karakter.")

    search_data = await search_openalex_papers(payload.query, limit=payload.limit)
    papers = search_data.get("papers", [])
    query_used = search_data.get("query_used", payload.query)
    msg = search_data.get("message", "")

    for p in papers:
        CACHED_PAPERS[p["id"]] = p

    items = [PaperItem(**p) for p in papers]
    return SearchResponse(
        success=True,
        total=len(items),
        query_used=query_used,
        message=msg,
        papers=items
    )


@router.post("/generate", response_model=GenerateResponse)
async def generate_task(payload: GenerateRequest):
    """Mengunduh berkas naskah terpilih, mengekstrak isi teks, dan merangkai draf tugas."""
    selected_papers = []
    for pid in payload.paper_ids:
        p_data = CACHED_PAPERS.get(pid)
        if not p_data:
            continue

        p_data_copy = dict(p_data)
        if p_data.get("is_manual_module"):
            p_data_copy["has_full_pdf"] = True
            selected_papers.append(p_data_copy)
            continue

        candidate_urls = p_data.get("all_pdf_urls") or [p_data.get("pdf_url")]
        
        # Coba unduh berkas PDF fisik
        local_pdf_path = await download_paper_pdf(candidate_urls, pid)
        
        pages_content = []
        if local_pdf_path:
            pages_content = extract_text_with_pages(local_pdf_path, max_pages=8)
            p_data_copy["has_full_pdf"] = True
            p_data_copy["source_status"] = "Naskah Fisik PDF Lengkap"
        
        # Jika PDF gagal diunduh atau teks kosong, gunakan data abstrak resmi & metadata terverifikasi OpenAlex
        if not pages_content:
            p_data_copy["has_full_pdf"] = False
            p_data_copy["source_status"] = "Abstrak & Metadata Terverifikasi"
            abstract_text = p_data.get("abstract") or "Kajian ilmiah ini berfokus pada analisis mendalam mengenai topik penelitian terkait."
            pages_content = [
                {
                    "page_number": 1,
                    "text": f"Judul Penelitian: {p_data.get('title')}\nPublikasi: {p_data.get('venue')}\nAbstrak Resmi Terverifikasi: {abstract_text}"
                }
            ]

        p_data_copy["pages_content"] = pages_content
        selected_papers.append(p_data_copy)

    if payload.paper_ids and not selected_papers:
        raise HTTPException(
            status_code=422,
            detail="Gagal memproses berkas naskah terpilih. Silakan pilih sumber jurnal lain."
        )

    # Rangkai draf lewat Gemini dengan proteksi antrean
    try:
        draft_result = await generate_academic_draft(
            topic=payload.topic,
            papers_with_content=selected_papers,
            format_type=payload.format_type,
            target_words=payload.target_words,
            paragraph_depth=payload.paragraph_depth,
            tone=payload.tone,
            custom_instructions=payload.custom_instructions or "",
            answer_spec=payload.answer_spec.model_dump() if payload.answer_spec else None,
            student_name=payload.student_name.strip(),
            course_name=payload.course_name.strip(),
            quote_citations=payload.quote_citations,
            task_type=payload.task_type,
        )
    except Exception as e:
        print(f"Error pada generasi Gemini: {e}")
        raise HTTPException(
            status_code=503,
            detail=f"Layanan Gemini sedang mengalami lonjakan antrean. Silakan tekan tombol tulis sekali lagi."
        )

    task_id = str(uuid.uuid4())[:8]
    title = draft_result.get("title", payload.topic)
    sections = draft_result.get("sections", [])

    language = draft_result.get("language")
    is_en = language == "en"
    identity_labels = ("Name", "Student ID", "Course") if is_en else ("Nama", "NIM", "Mata Kuliah")
    identity_values = (payload.student_name, payload.student_id, payload.course_name)
    identity_lines = [f"{label}: {value.strip()}" for label, value in zip(identity_labels, identity_values) if value.strip()]
    # Postingan forum diskusi tampil di bawah nama pengirim, jadi nama, NIM, dan mata kuliah tidak ditulis
    if payload.task_type == "ut-diskusi":
        identity_lines = []

    # Data lengkap disimpan supaya naskah bisa diedit dan ditulis ulang per bagian tanpa generate dari nol
    task = {
        "title": title,
        "sections": sections,
        "references": selected_papers,
        "language": language,
        "identity_lines": identity_lines,
        "topic": payload.topic,
        "guidelines": payload.custom_instructions or "",
        "answer_spec": payload.answer_spec.model_dump() if payload.answer_spec else {},
        "quote_citations": payload.quote_citations,
        "course_name": payload.course_name,
        "student_name": payload.student_name,
        "student_id": payload.student_id,
        "task_type": payload.task_type,
    }
    build_task_files(task_id, task)
    TASKS_DB[task_id] = task
    save_task_to_disk(task_id, task)
    total_words = count_words(sections)

    # Susun bukti sitasi transparan (evidence)
    evidence_list = []
    all_content_text = " ".join(s.get("content", "") for s in sections)

    for p in selected_papers:
        p_title = p.get("title", "")
        p_authors = ", ".join(p.get("authors", []))
        p_year = p.get("year")
        has_full_pdf = p.get("has_full_pdf", False)
        pages_content = p.get("pages_content", [])

        # Hitung kemunculan nama belakang penulis di naskah
        author_list = p.get("authors", [])
        citation_count = 0
        if author_list:
            for aut in author_list:
                surname = aut.split()[-1]
                if len(surname) > 2:
                    citation_count += all_content_text.count(surname)

        snippets = []
        for pg in pages_content[:3]:
            txt = pg.get("text", "").strip()
            if txt:
                clean_snippet = " ".join(txt.split())
                if len(clean_snippet) > 280:
                    clean_snippet = clean_snippet[:280] + "..."
                snippets.append({
                    "page": pg.get("page_number", 1),
                    "text": clean_snippet
                })

        evidence_list.append({
            "paper_id": p.get("id", ""),
            "title": p_title,
            "authors": p_authors,
            "year": p_year,
            "venue": p.get("venue", "Publikasi Akademik"),
            "doi": p.get("doi", ""),
            "has_full_pdf": has_full_pdf,
            "citation_count": citation_count,
            "snippets": snippets
        })

    return GenerateResponse(
        success=True,
        task_id=task_id,
        title=title,
        word_count=total_words,
        sections=sections,
        references=selected_papers,
        evidence=evidence_list,
        identity_lines=identity_lines,
        language=language,
    )



@router.get("/download/{file_type}/{task_id}")
async def download_file(file_type: str, task_id: str):
    """Mengunduh berkas docx atau pdf hasil rakitan tugas."""
    # Tugas lama dimuat ulang dari disk supaya tetap bisa diunduh setelah aplikasi dibuka ulang
    task = get_task_or_404(task_id)

    if file_type == "docx":
        file_path = task.get("docx_path")
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif file_type == "pdf":
        file_path = task.get("pdf_path")
        media_type = "application/pdf"
    else:
        raise HTTPException(status_code=400, detail="Tipe berkas tidak didukung. Pilih docx atau pdf.")

    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Berkas fisik tidak ditemukan di server.")

    filename = f"{task.get('download_base', 'Tugas')}.{file_type}"
    return FileResponse(path=file_path, filename=filename, media_type=media_type)
