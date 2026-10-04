import re
from typing import Dict, Any, List, Optional

INSTITUTIONAL_KEYWORDS = {
    "universitas", "kementerian", "badan", "lembaga", "organisasi",
    "bureau", "department", "ministry", "organization", "institute",
    "university", "press", "center", "centre", "who", "unesco",
    "anonim", "anonymous"
}


def format_single_author_apa(author: str) -> str:
    """
    Mengubah nama penulis ke format standar sitasi APA (NamaBelakang, Inisial.).
    Contoh: 'Willa Cather' -> 'Cather, W.'
    Contoh: 'Budi Santoso' -> 'Santoso, B.'
    Contoh: 'John Maynard Keynes' -> 'Keynes, J. M.'
    Jika berupa nama institusi atau nama tunggal, dipertahankan utuh.
    """
    if not author or not author.strip():
        return "Anonim"

    clean_author = " ".join(author.strip().split())
    lower_author = clean_author.lower()

    # Periksa apakah nama merupakan nama institusi atau lembaga
    if any(k in lower_author for k in INSTITUTIONAL_KEYWORDS):
        return clean_author

    # Jika nama sudah memiliki koma (misal 'Cather, Willa' atau 'Doe, J.')
    if "," in clean_author:
        parts = clean_author.split(",", 1)
        surname = parts[0].strip()
        first_parts = parts[1].strip().split()
        if not first_parts:
            return surname
        initials = " ".join(f"{p[0].upper()}." for p in first_parts if p)
        return f"{surname}, {initials}"

    tokens = clean_author.split()
    if len(tokens) == 1:
        # Nama tunggal (misal 'Soekarno', 'Plato')
        return clean_author

    # Nama majemuk: ambil kata terakhir sebagai nama keluarga
    surname = tokens[-1]
    initials = " ".join(f"{t[0].upper()}." for t in tokens[:-1] if t)
    return f"{surname}, {initials}"


def format_authors_apa(authors: Optional[List[str]]) -> str:
    """
    Menyusun daftar penulis ke format APA 7th dengan tanda ampersand (&).
    Contoh 1 penulis: 'Cather, W.'
    Contoh 2 penulis: 'Santoso, B., & Aminah, S.'
    Contoh 3 penulis: 'Santoso, B., Aminah, S., & Wijaya, H.'
    """
    if not authors:
        return "Anonim"

    formatted = [format_single_author_apa(a) for a in authors if a and a.strip()]
    if not formatted:
        return "Anonim"

    if len(formatted) == 1:
        return formatted[0]
    if len(formatted) == 2:
        return f"{formatted[0]}, & {formatted[1]}"
    
    return f"{', '.join(formatted[:-1])}, & {formatted[-1]}"


def format_doi_url(doi: Optional[str]) -> str:
    """Mengubah kode DOI menjadi tautan HTTPS resmi yang dapat diakses."""
    if not doi or not doi.strip():
        return ""
    clean = doi.strip()
    if clean.startswith("http://") or clean.startswith("https://"):
        return clean
    clean = clean.lstrip("/")
    return f"https://doi.org/{clean}"


def build_academic_reference_data(ref: Dict[str, Any], is_en: bool = False) -> Dict[str, str]:
    """
    Menyusun komponen referensi daftar pustaka lengkap standar APA 7th.
    Mengembalikan dictionary berisi komponen teks terstruktur untuk perakit dokumen Word, PDF, dan Web.
    """
    authors = ref.get("authors") or []
    author_str = format_authors_apa(authors)
    year = ref.get("year") or "n.d."
    title = (ref.get("title") or "Tanpa Judul").strip().rstrip(".")
    venue = (ref.get("venue") or "").strip().rstrip(".")
    doi = format_doi_url(ref.get("doi"))

    volume = str(ref.get("volume") or "").strip()
    issue = str(ref.get("issue") or "").strip()
    pages = str(ref.get("pages") or "").strip()
    page_info = str(ref.get("page_info") or "").strip().rstrip(".")

    # Susun detail publikasi berkala (jurnal atau bahan kuliah)
    pub_details = ""
    if volume and issue and pages:
        pub_details = f"{volume}({issue}), {pages}"
    elif volume and pages:
        pub_details = f"{volume}, {pages}"
    elif volume and issue:
        pub_details = f"{volume}({issue})"
    elif pages:
        prefix = "pp. " if is_en else "hlm. "
        pub_details = f"{prefix}{pages}"
    elif page_info:
        pub_details = page_info

    author_lead = author_str.rstrip(".") + "."
    parts = [f"{author_lead} ({year}). {title}."]

    if venue and pub_details:
        parts.append(f"{venue}, {pub_details}.")
    elif venue:
        parts.append(f"{venue}.")
    elif pub_details:
        parts.append(f"{pub_details}.")

    if doi:
        parts.append(doi)
    elif ref.get("scholar_url") and not ref.get("is_ut_bmp"):
        pass

    full_citation = " ".join(parts)

    return {
        "authors": author_str,
        "year": str(year),
        "title": title,
        "venue": venue,
        "pub_details": pub_details,
        "doi": doi,
        "full_text": full_citation
    }
