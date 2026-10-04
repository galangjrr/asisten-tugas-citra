import datetime
from typing import Any, Dict, List, Optional

from google.genai import types

from agents.generator import robust_json_dict_parse
from tools.gemini_client import generate_with_fallback

LOOKUP_PROMPT = """Cari di internet informasi terbit PERTAMA karya berikut untuk daftar pustaka APA.
Judul: {title}
Penulis menurut pengguna: {author}

Aturan:
- "year" adalah tahun karya ini PERTAMA kali terbit, bukan tahun cetak ulang, edisi baru, terjemahan, atau tanggal unggah situs. Cerpen sering terbit pertama di majalah atau surat kabar.
- "venue" adalah nama majalah, surat kabar, buku kumpulan, atau penerbit tempat karya itu pertama terbit.
- "author" adalah nama lengkap penulis sesuai sumber.
- Jika sumber tidak menyebut dengan jelas, isi null. DILARANG menebak.
- "note" berisi satu kalimat bahasa Indonesia tentang dasar jawabanmu, misal 'Terbit pertama di The Home Monthly edisi Desember 1896'.

Jawab HANYA JSON murni tanpa teks lain:
{{"author": "...", "year": 1896, "venue": "...", "note": "..."}}"""


def _sources(response: Any) -> List[Dict[str, str]]:
    """Mengambil halaman web yang benar-benar dibaca Google Search, supaya pengguna bisa mengecek sendiri."""
    try:
        chunks = response.candidates[0].grounding_metadata.grounding_chunks or []
    except (AttributeError, IndexError, TypeError):
        return []
    found = []
    for chunk in chunks:
        web = getattr(chunk, "web", None)
        if web and web.uri and all(s["uri"] != web.uri for s in found):
            found.append({"title": (web.title or web.uri)[:120], "uri": web.uri})
    return found[:3]


def _clean_text(value: Any, limit: int) -> Optional[str]:
    text = " ".join(str(value).split()) if isinstance(value, str) else ""
    return text[:limit] if text and text.lower() not in ("null", "none", "-") else None


async def lookup_publication(title: str, author: str = "") -> Dict[str, Any]:
    """
    Mencari penulis, tahun terbit pertama, dan tempat terbit lewat Gemini dengan Google Search. Satu panggilan per pencarian.
    Jawaban tanpa sumber web dianggap tidak ditemukan, karena model tanpa pencarian bisa mengarang tahun.
    """
    title = (title or "").strip()
    if len(title) < 3:
        raise ValueError("Judul naskah minimal 3 huruf.")

    response = await generate_with_fallback(
        "fast",
        LOOKUP_PROMPT.format(title=title, author=(author or "").strip() or "tidak diketahui"),
        config=types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())], temperature=0),
        timeout=40.0,
        total_budget=60.0,
    )
    sources = _sources(response)
    parsed = robust_json_dict_parse(response.text) or {}

    try:
        year = int(parsed.get("year"))
    except (TypeError, ValueError):
        year = None
    if year is not None and not 1000 <= year <= datetime.date.today().year:
        year = None

    result = {
        "author": _clean_text(parsed.get("author"), 150),
        "year": year,
        "venue": _clean_text(parsed.get("venue"), 200),
        "note": _clean_text(parsed.get("note"), 300) or "",
        "sources": sources,
    }
    result["found"] = bool(sources) and any(result[k] for k in ("author", "year", "venue"))
    if not sources:
        result.update(author=None, year=None, venue=None, note="Tidak ada sumber web yang bisa dicek, jadi hasilnya tidak dipakai.")
    return result
