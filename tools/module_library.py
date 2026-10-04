import os
import sys
import json
import re
import uuid
from typing import List, Dict, Any, Optional

def get_saved_modules_dirs() -> List[str]:
    """Mengembalikan daftar direktori tempat berkas modul tersimpan dicari."""
    dirs = []
    
    # 1. Saat dibungkus PyInstaller (frozen exe)
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        dirs.append(os.path.join(exe_dir, "saved_modules"))
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            dirs.append(os.path.join(meipass, "saved_modules"))
    
    # 2. Direktori proyek saat ini
    cwd = os.getcwd()
    dirs.append(os.path.join(cwd, "saved_modules"))
    dirs.append(os.path.join(cwd, "storage", "modules"))
    
    # 3. Direktori berkas ini
    module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dirs.append(os.path.join(module_dir, "saved_modules"))
    dirs.append(os.path.join(module_dir, "storage", "modules"))

    # Hilangkan duplikasi sambil mempertahankan urutan
    seen = set()
    valid_dirs = []
    for d in dirs:
        norm = os.path.normpath(os.path.abspath(d))
        if norm not in seen:
            seen.add(norm)
            valid_dirs.append(norm)
    return valid_dirs


def ensure_saved_modules_dir() -> str:
    """Memastikan direktori utama saved_modules ada dan mengembalikan path-nya."""
    if getattr(sys, "frozen", False):
        target = os.path.join(os.path.dirname(sys.executable), "saved_modules")
    else:
        target = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "saved_modules")
    os.makedirs(target, exist_ok=True)
    return target


def list_saved_modules() -> List[Dict[str, Any]]:
    """
    Memindai seluruh modul yang tersimpan di direktori saved_modules.
    Mengembalikan metadata ringkas untuk ditampilkan di antarmuka.
    """
    modules = []
    seen_ids = set()

    for d in get_saved_modules_dirs():
        if not os.path.exists(d):
            continue
        try:
            for fname in os.listdir(d):
                if not fname.lower().endswith(".json"):
                    continue
                fpath = os.path.join(d, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as fh:
                        data = json.load(fh)
                    
                    mod_id = data.get("id") or fname[:-5]
                    if mod_id in seen_ids:
                        continue
                    seen_ids.add(mod_id)

                    title = data.get("title") or fname[:-5].replace("_", " ")
                    authors = data.get("authors") or []
                    year = data.get("year")
                    venue = data.get("venue") or ""
                    pages = data.get("pages_content") or []
                    total_chars = sum(len(p.get("text", "")) for p in pages)

                    modules.append({
                        "id": mod_id,
                        "filename": fname,
                        "title": title,
                        "authors": authors,
                        "year": year,
                        "venue": venue,
                        "source_status": data.get("source_status", "Buku Materi Pokok UT"),
                        "chunk_count": len(pages),
                        "char_count": total_chars,
                        "abstract": data.get("abstract", "")[:200],
                        "file_path": fpath
                    })
                except Exception as e:
                    print(f"Peringatan: Gagal membaca modul tersimpan {fpath}: {e}")
        except Exception:
            pass

    # Urutkan berdasarkan judul
    modules.sort(key=lambda m: m["title"].lower())
    return modules


def load_saved_module(module_identifier: str) -> Optional[Dict[str, Any]]:
    """
    Memuat isi lengkap modul tersimpan berdasarkan ID atau nama berkas.
    Mengembalikan kamus data lengkap yang siap didaftarkan ke CACHED_PAPERS.
    """
    target = module_identifier.strip()
    if not target:
        return None

    for d in get_saved_modules_dirs():
        if not os.path.exists(d):
            continue
        
        # Coba cocokkan nama berkas langsung
        candidate_files = [
            os.path.join(d, target),
            os.path.join(d, f"{target}.json"),
        ]
        for cf in candidate_files:
            if os.path.isfile(cf):
                try:
                    with open(cf, "r", encoding="utf-8") as fh:
                        return json.load(fh)
                except Exception:
                    pass

        # Cari berdasarkan id di dalam berkas JSON
        try:
            for fname in os.listdir(d):
                if not fname.lower().endswith(".json"):
                    continue
                fpath = os.path.join(d, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as fh:
                        data = json.load(fh)
                    if data.get("id") == target or fname[:-5] == target:
                        return data
                except Exception:
                    pass
        except Exception:
            pass

    return None


def save_module_to_library(
    title: str,
    author: Optional[str] = None,
    year: Optional[int] = None,
    venue: Optional[str] = None,
    page_info: Optional[str] = None,
    content_text: str = "",
    is_ut_bmp: bool = True
) -> Dict[str, Any]:
    """
    Menyimpan modul baru ke direktori saved_modules dalam format JSON.
    Mengembalikan data modul yang tersimpan.
    """
    from tools.reading_doc_reader import split_marked_pages
    from tools.content_chunker import chunk_paragraphs

    target_dir = ensure_saved_modules_dir()

    clean_title = re.sub(r"[^\w\s-]", "", title).strip()
    slug = re.sub(r"[-\s]+", "_", clean_title)[:60]
    if not slug:
        slug = f"modul_{uuid.uuid4().hex[:8]}"

    pages_raw = split_marked_pages(content_text)
    pages_content = []
    chunk_index = 1
    for label, body in pages_raw:
        for chunk in chunk_paragraphs(body):
            page_label = label or f"Bagian {chunk_index}"
            pages_content.append({"page_number": page_label, "text": chunk})
            chunk_index += 1

    authors = [author.strip()] if author and author.strip() else (["Universitas Terbuka"] if is_ut_bmp else [])
    mod_id = f"bmp_{uuid.uuid4().hex[:8]}"
    abstract = " ".join(" ".join(p["text"] for p in pages_content[:2]).split())[:400]

    module_data = {
        "id": mod_id,
        "title": title.strip(),
        "authors": authors,
        "year": year,
        "venue": venue.strip() if venue else ("Buku Materi Pokok (BMP) Universitas Terbuka" if is_ut_bmp else ""),
        "doi": "",
        "pdf_url": "",
        "all_pdf_urls": [],
        "abstract": abstract,
        "scholar_url": "https://pustaka.ut.ac.id/" if is_ut_bmp else "",
        "has_full_pdf": True,
        "is_manual_module": True,
        "is_ut_bmp": is_ut_bmp,
        "source_status": "Buku Materi Pokok UT" if is_ut_bmp else "Bahan bacaan dosen",
        "page_info": page_info.strip() if page_info else "",
        "pages_content": pages_content,
    }

    file_path = os.path.join(target_dir, f"{slug}.json")
    with open(file_path, "w", encoding="utf-8") as fh:
        json.dump(module_data, fh, ensure_ascii=False, indent=2)

    return module_data
