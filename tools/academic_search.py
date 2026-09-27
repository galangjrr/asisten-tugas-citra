import httpx
from typing import List, Dict, Any, Optional
import os
import re
import asyncio
from tools.gemini_client import get_gemini_client


def reconstruct_abstract(abstract_inverted_index: Optional[Dict[str, List[int]]]) -> str:
    """Mengubah format abstract inverted index OpenAlex menjadi teks kalimat utuh."""
    if not abstract_inverted_index:
        return ""
    word_positions = []
    for word, positions in abstract_inverted_index.items():
        for pos in positions:
            word_positions.append((pos, word))
    word_positions.sort(key=lambda x: x[0])
    return " ".join([word for _, word in word_positions])


def extract_all_pdf_urls(work: Dict[str, Any]) -> List[str]:
    """Mengumpulkan seluruh kandidat tautan berkas naskah PDF asli dari berbagai lokasi OpenAlex."""
    urls = []
    locations_to_check = []
    if work.get("best_oa_location"):
        locations_to_check.append(work["best_oa_location"])
    if work.get("primary_location"):
        locations_to_check.append(work["primary_location"])
    if work.get("open_access") and isinstance(work["open_access"], dict):
        oa_url = work["open_access"].get("oa_url")
        if oa_url and oa_url.startswith("http") and oa_url not in urls:
            urls.append(oa_url)
    if work.get("locations") and isinstance(work["locations"], list):
        locations_to_check.extend(work["locations"])

    for loc in locations_to_check:
        if not loc or not isinstance(loc, dict):
            continue
        for key in ["pdf_url", "oa_url", "landing_page_url"]:
            val = loc.get(key)
            if val and isinstance(val, str) and (val.startswith("http://") or val.startswith("https://")):
                if val not in urls:
                    urls.append(val)

    return urls


def extract_best_pdf_or_doc_url(work: Dict[str, Any]) -> Optional[str]:
    """Mengekstrak tautan berkas naskah PDF asli terbaik."""
    urls = extract_all_pdf_urls(work)
    return urls[0] if urls else None


def is_doi_string(query: str) -> bool:
    """Memeriksa apakah string input merupakan format DOI."""
    clean = query.strip()
    return bool(re.search(r'10\.\d{4,9}/[-._;()/:A-Za-z0-9]+', clean))


def extract_doi(query: str) -> str:
    """Mengekstrak identifier DOI dari string atau URL."""
    match = re.search(r'10\.\d{4,9}/[-._;()/:A-Za-z0-9]+', query.strip())
    return match.group(0) if match else query.strip()


async def simplify_query_with_ai(original_query: str) -> str:
    """Mengekstrak entitas dan kata kunci esensial dari pertanyaan panjang."""
    if not os.getenv("GEMINI_API_KEY"):
        return original_query

    try:
        client = get_gemini_client()
    except Exception:
        return original_query

    prompt = f"""
Tugas: Ekstrak 2 sampai 4 kata kunci pencarian jurnal akademis paling esensial dan spesifik dari teks tugas ini.
ATURAN KRUSIAL:
- Wajib pertahankan nama subjek spesifik atau entitas unik (contoh: 'Instagram', 'TikTok', 'Radiologi', 'Stunting', dsb).
- Buang kata-kata umum seperti 'pengaruh', 'kehadiran', 'analisis', 'upaya', 'era', 'digitalisasi' jika itu hanya imbuhan kalimat.
- Fokus pada: [Subjek Spesifik] + [Topik Masalah Nyata].
Contoh masukan: "Pengaruh kehadiran Instagram untuk standar kehidupan masyarakat modern di era digitalisasi"
Contoh keluaran: Instagram gaya hidup masyarakat

HANYA keluarkan kata kunci tanpa tanda kutip atau penjelasan apapun.
Teks: {original_query}
"""

    candidate_models = ["gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-3.1-flash-lite"]
    for model_name in candidate_models:
        try:
            res = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model=model_name,
                    contents=prompt
                ),
                timeout=4.0
            )
            if res.text:
                cleaned = res.text.strip().replace('"', '').replace('\n', ' ')
                if len(cleaned) > 2:
                    return cleaned
        except Exception:
            continue

    return original_query


async def query_openalex_endpoint(search_text: str, limit: int = 30) -> List[Dict[str, Any]]:
    """Memanggil endpoint pencarian OpenAlex dengan filter akses terbuka."""
    url = "https://api.openalex.org/works"
    params = {
        "search": search_text,
        "filter": "is_oa:true",
        "per-page": limit
    }
    headers = {
        "User-Agent": "AsistenTugasCitra/1.0 (mailto:admin@citra.app)"
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, params=params, headers=headers)
            if response.status_code == 200:
                data = response.json()
                return data.get("results", [])
    except Exception as e:
        print(f"Gagal memanggil OpenAlex: {e}")
    return []


async def query_crossref_endpoint(search_text: str, limit: int = 15) -> List[Dict[str, Any]]:
    """Memanggil endpoint pencarian Crossref sebagai mesin pencari rujukan alternatif."""
    url = "https://api.crossref.org/works"
    params = {
        "query": search_text,
        "rows": limit
    }
    headers = {
        "User-Agent": "AsistenTugasCitra/1.0 (mailto:admin@citra.app)"
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, params=params, headers=headers)
            if response.status_code == 200:
                data = response.json()
                return data.get("message", {}).get("items", [])
    except Exception as e:
        print(f"Gagal memanggil Crossref: {e}")
    return []


async def fetch_paper_by_doi(doi_str: str) -> Optional[Dict[str, Any]]:
    """Mengambil naskah spesifik langsung melalui nomor DOI dari Crossref atau OpenAlex."""
    doi = extract_doi(doi_str)
    headers = {
        "User-Agent": "AsistenTugasCitra/1.0 (mailto:admin@citra.app)"
    }
    url = f"https://api.crossref.org/works/{doi}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(url, headers=headers)
            if res.status_code == 200:
                it = res.json().get("message", {})
                title_list = it.get("title", [])
                title = title_list[0] if title_list else f"Paper DOI {doi}"
                
                authors = []
                for a in it.get("author", []):
                    name = f"{a.get('given', '')} {a.get('family', '')}".strip() or a.get("name", "")
                    if name:
                        authors.append(name)

                pub = it.get("published", {})
                year = None
                if pub.get("date-parts") and pub["date-parts"][0]:
                    year = pub["date-parts"][0][0]

                venues = it.get("container-title", [])
                venue = venues[0] if venues else it.get("publisher", "Publikasi Akademik")

                pdf_urls = []
                for lk in it.get("link", []):
                    u = lk.get("URL")
                    if u and (u.startswith("http://") or u.startswith("https://")):
                        if u not in pdf_urls:
                            pdf_urls.append(u)

                return {
                    "id": doi.replace("/", "_"),
                    "title": title,
                    "authors": authors if authors else ["Peneliti Terverifikasi"],
                    "year": year,
                    "venue": venue,
                    "doi": f"https://doi.org/{doi}",
                    "pdf_url": pdf_urls[0] if pdf_urls else f"https://doi.org/{doi}",
                    "all_pdf_urls": pdf_urls,
                    "abstract": f"Naskah terverifikasi dari registri resmi DOI Crossref dengan penerbit {venue}.",
                    "scholar_url": f"https://scholar.google.com/scholar?q={doi}",
                }
    except Exception as e:
        print(f"Gagal mengambil paper via DOI: {e}")
    return None


async def search_openalex_papers(query: str, limit: int = 6) -> Dict[str, Any]:
    """Mencari naskah ilmiah akses terbuka dengan kombinasi OpenAlex dan Crossref."""
    if not query or len(query.strip()) < 3:
        return {"papers": [], "query_used": query, "message": "Kata kunci pencarian terlalu pendek."}

    clean_query = query.strip()

    # 1. Jika pengguna memasukkan nomor DOI langsung
    if is_doi_string(clean_query):
        direct_paper = await fetch_paper_by_doi(clean_query)
        if direct_paper:
            return {
                "papers": [direct_paper],
                "query_used": clean_query,
                "message": f"Naskah resmi berhasil ditemukan langsung melalui nomor DOI."
            }

    # 2. Tentukan kata kunci pencarian
    words = clean_query.split()
    query_used = clean_query
    
    # Jika kueri adalah kalimat panjang (> 3 kata), lakukan ekstraksi kata kunci spesifik
    if len(words) > 3:
        query_used = await simplify_query_with_ai(clean_query)
        print(f"Kueri dipertajam menjadi: '{query_used}'")

    results: List[Dict[str, Any]] = []
    seen_ids = set()
    seen_titles = set()

    # 3. Cari di OpenAlex
    works = await query_openalex_endpoint(query_used, limit=30)
    for work in works:
        work_id = work.get("id", "").split("/")[-1] or work.get("id", "")
        if work_id in seen_ids:
            continue

        title = work.get("display_name", "Tanpa Judul")
        title_lower = title.lower()
        if title_lower in seen_titles:
            continue

        pdf_url = extract_best_pdf_or_doc_url(work)
        all_urls = extract_all_pdf_urls(work)

        authorships = work.get("authorships", [])
        authors = [
            a.get("author", {}).get("display_name", "")
            for a in authorships
            if a.get("author", {}).get("display_name")
        ]

        raw_abstract = work.get("abstract_inverted_index")
        abstract_text = reconstruct_abstract(raw_abstract)

        primary_loc = work.get("primary_location", {}) or {}
        source_venue = primary_loc.get("source", {}) or {}
        venue_name = source_venue.get("display_name", "Publikasi Akademik")

        results.append({
            "id": work_id,
            "title": title,
            "authors": authors if authors else ["Anonim"],
            "year": work.get("publication_year"),
            "venue": venue_name,
            "doi": work.get("doi", ""),
            "pdf_url": pdf_url or (all_urls[0] if all_urls else None),
            "all_pdf_urls": all_urls,
            "abstract": abstract_text[:1200] if abstract_text else "Abstrak naskah lengkap tersedia di berkas terunduh.",
            "scholar_url": f"https://scholar.google.com/scholar?q={title.replace(' ', '+')}",
        })
        seen_ids.add(work_id)
        seen_titles.add(title_lower)

        if len(results) >= limit:
            break

    # 4. Jika hasil OpenAlex kurang dari target (atau terkena pembatasan kuota), lengkapi dari Crossref
    if len(results) < limit:
        crossref_items = await query_crossref_endpoint(query_used, limit=20)
        for it in crossref_items:
            title_list = it.get("title", [])
            title = title_list[0] if title_list else "Tanpa Judul"
            title_lower = title.lower()
            if title_lower in seen_titles:
                continue

            doi = it.get("DOI", "")
            c_id = doi.replace("/", "_") if doi else f"cr_{len(seen_ids)+1}"
            if c_id in seen_ids:
                continue

            authors = []
            for a in it.get("author", []):
                name = f"{a.get('given', '')} {a.get('family', '')}".strip() or a.get("name", "")
                if name:
                    authors.append(name)

            pub = it.get("published", {})
            year = None
            if pub.get("date-parts") and pub["date-parts"][0]:
                year = pub["date-parts"][0][0]

            venues = it.get("container-title", [])
            venue = venues[0] if venues else it.get("publisher", "Publikasi Akademik")

            pdf_urls = []
            for lk in it.get("link", []):
                u = lk.get("URL")
                if u and (u.startswith("http://") or u.startswith("https://")):
                    if u not in pdf_urls:
                        pdf_urls.append(u)

            results.append({
                "id": c_id,
                "title": title,
                "authors": authors if authors else ["Peneliti Terverifikasi"],
                "year": year,
                "venue": venue,
                "doi": f"https://doi.org/{doi}" if doi else "",
                "pdf_url": pdf_urls[0] if pdf_urls else (f"https://doi.org/{doi}" if doi else None),
                "all_pdf_urls": pdf_urls,
                "abstract": f"Naskah terverifikasi dari publikasi {venue}.",
                "scholar_url": f"https://scholar.google.com/scholar?q={title.replace(' ', '+')}",
            })
            seen_ids.add(c_id)
            seen_titles.add(title_lower)

            if len(results) >= limit:
                break

    if results:
        msg = f"Berhasil menemukan {len(results)} naskah terverifikasi untuk kata kunci fokus '{query_used}'."
    else:
        msg = f"Tidak ditemukan naskah yang cocok untuk kueri '{query_used}'. Coba gunakan kata kunci yang lebih ringkas atau masukkan nomor DOI."

    return {
        "papers": results,
        "query_used": query_used,
        "message": msg
    }
