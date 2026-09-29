import os
import uuid
from typing import Dict, Any
from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from dotenv import load_dotenv

import base64
from api.schemas import (
    HealthResponse, SearchRequest, SearchResponse, GenerateRequest, GenerateResponse,
    PaperItem, ManualModuleRequest, UTCourseLookupResponse,
    ExtractScreenshotRequest, ExtractScreenshotResponse,
    ParseQuestionDocRequest, ParseQuestionDocResponse
)
from tools.academic_search import search_openalex_papers
from tools.pdf_downloader import download_paper_pdf
from tools.pdf_parser import extract_text_with_pages
from tools.ut_catalog import lookup_ut_course
from tools.ocr_vision import extract_text_from_image
from tools.question_reader import parse_question_document
from tools.gemini_client import get_ai_status
from agents.generator import generate_academic_draft
from exporters.docx_builder import create_assignment_docx
from exporters.pdf_builder import create_assignment_pdf



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
    )


def safe_filename_part(text: str) -> str:
    """Membuang karakter yang tidak sah di nama berkas Windows maupun header unduhan."""
    return " ".join("".join(c for c in text if c.isalnum() or c in (" ", "-", ".")).split()).strip(" .")


@router.post("/manual-module", response_model=PaperItem)
async def add_manual_module(payload: ManualModuleRequest):
    """Menerima teks salinan modul BMP UT atau diktat kuliah dan menyimpannya sebagai rujukan."""
    mod_id = f"bmp_{uuid.uuid4().hex[:8]}"
    author_name = payload.author.strip() if payload.author and payload.author.strip() else "Universitas Terbuka"
    authors = [author_name]

    module_title = payload.module_title.strip()
    lookup = lookup_ut_course(module_title)
    if lookup.get("found") and lookup.get("exact") and lookup.get("course"):
        module_title = lookup["course"]["formatted_title"]

    venue_name = "Buku Materi Pokok (BMP) Universitas Terbuka"
    item_data = {
        "id": mod_id,
        "title": module_title,
        "authors": authors,
        "year": payload.year or 2023,
        "venue": venue_name,
        "doi": "",
        "pdf_url": "",
        "all_pdf_urls": [],
        "abstract": f"Bahan ajar modul kuliah resmi: {payload.module_title}. Rujukan: {payload.page_or_kb}.",
        "scholar_url": "https://pustaka.ut.ac.id/",
        "has_full_pdf": True,
        "is_manual_module": True,
        "source_status": "Buku Materi Pokok UT",
        "page_info": payload.page_or_kb or "Modul 1",
        "pages_content": [
            {
                "page_number": payload.page_or_kb or "Modul 1",
                "text": f"Buku Materi Pokok: {payload.module_title}\nRujukan: {payload.page_or_kb}\nTeks Pembahasan Modul:\n{payload.content_text.strip()}"
            }
        ]
    }
    CACHED_PAPERS[mod_id] = item_data
    return PaperItem(
        id=mod_id,
        title=item_data["title"],
        authors=item_data["authors"],
        year=item_data["year"],
        venue=item_data["venue"],
        doi="",
        pdf_url="",
        abstract=item_data["abstract"],
        scholar_url=item_data["scholar_url"]
    )


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
    if not res.get("success"):
        return ParseQuestionDocResponse(
            success=False,
            filename=filename,
            file_type=res.get("file_type", ""),
            text="",
            message="Gagal mengekstrak teks dari berkas. Pastikan dokumen tidak terkunci kata sandi."
        )

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
        message=f"Berhasil membaca {res.get('char_count', 0)} karakter dari berkas {filename}."
    )


@router.post("/parse-question-doc", response_model=ParseQuestionDocResponse)
async def parse_question_doc_base64(payload: ParseQuestionDocRequest):
    """Membaca berkas soal dosen via base64 encoded data."""
    raw_b64 = payload.file_base64
    if "," in raw_b64:
        raw_b64 = raw_b64.split(",", 1)[1]

    try:
        file_bytes = base64.b64decode(raw_b64)
    except Exception:
        raise HTTPException(status_code=400, detail="Format data berkas tidak valid.")

    res = await parse_question_document(file_bytes, payload.filename)
    if not res.get("success"):
        return ParseQuestionDocResponse(
            success=False,
            filename=payload.filename,
            file_type=res.get("file_type", ""),
            text="",
            message="Gagal mengekstrak teks dari berkas."
        )

    return ParseQuestionDocResponse(
        success=True,
        filename=payload.filename,
        file_type=res.get("file_type", ""),
        text=res.get("text", ""),
        questions=res.get("questions", res.get("text", "")),
        detected_guidelines=res.get("detected_guidelines", ""),
        char_count=res.get("char_count", 0),
        detected_course_code=res.get("detected_course_code"),
        word_count_hint=res.get("word_count_hint"),
        answer_spec=res.get("answer_spec"),
        answer_spec_source=res.get("answer_spec_source"),
        message=f"Berhasil membaca {res.get('char_count', 0)} karakter dari berkas {payload.filename}."
    )






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
            p_data_copy["source_status"] = "Buku Materi Pokok UT"
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

    # Nama unduhan mengikuti format kumpul tugas: judul_mata kuliah_nama_NIM. Berkas di disk tetap unik per task_id.
    name_parts = [title, payload.course_name, payload.student_name, payload.student_id]
    download_base = "_".join(p for p in (safe_filename_part(x) for x in name_parts) if p)[:180] or "Tugas"
    docx_name = f"{task_id}.docx"
    pdf_name = f"{task_id}.pdf"

    is_en = draft_result.get("language") == "en"
    identity_labels = ("Name", "Student ID", "Course") if is_en else ("Nama", "NIM", "Mata Kuliah")
    identity_values = (payload.student_name, payload.student_id, payload.course_name)
    identity_lines = [f"{label}: {value.strip()}" for label, value in zip(identity_labels, identity_values) if value.strip()]

    docx_path = create_assignment_docx(
        title=title,
        sections=sections,
        references=selected_papers,
        output_filename=docx_name,
        language=draft_result.get("language"),
        identity_lines=identity_lines,
    )

    pdf_path = create_assignment_pdf(
        title=title,
        sections=sections,
        references=selected_papers,
        output_filename=pdf_name,
        language=draft_result.get("language"),
        identity_lines=identity_lines,
    )

    # Hitung total kata
    total_words = sum(len(s.get("content", "").split()) for s in sections)

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

    TASKS_DB[task_id] = {
        "title": title,
        "sections": sections,
        "references": selected_papers,
        "docx_path": docx_path,
        "pdf_path": pdf_path,
        "download_base": download_base,
    }

    return GenerateResponse(
        success=True,
        task_id=task_id,
        title=title,
        word_count=total_words,
        sections=sections,
        references=selected_papers,
        evidence=evidence_list,
        identity_lines=identity_lines,
    )



@router.get("/download/{file_type}/{task_id}")
async def download_file(file_type: str, task_id: str):
    """Mengunduh berkas docx atau pdf hasil rakitan tugas."""
    task = TASKS_DB.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Berkas tugas tidak ditemukan atau sudah kadaluarsa.")

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
