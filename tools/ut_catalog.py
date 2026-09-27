import os
import json
import re
from pathlib import Path
from typing import Dict, Any, List, Optional

_CATALOG_CACHE: Optional[Dict[str, Dict[str, str]]] = None


COMMON_ALIASES: Dict[str, Dict[str, str]] = {
    "MKDU4110": {"kode": "MKDU4110", "nama": "Bahasa Indonesia", "edisi": "Edisi 2"},
    "MKDU4111": {"kode": "MKDU4111", "nama": "Pendidikan Kewarganegaraan", "edisi": "Edisi 2"},
    "MKDU4221": {"kode": "MKDU4221", "nama": "Pendidikan Agama Islam", "edisi": "Edisi 2"},
    "MKDU4222": {"kode": "MKDU4222", "nama": "Pendidikan Agama Kristen", "edisi": "Edisi 2"},
    "MKDU4223": {"kode": "MKDU4223", "nama": "Pendidikan Agama Katolik", "edisi": "Edisi 2"},
    "MKDU4224": {"kode": "MKDU4224", "nama": "Pendidikan Agama Hindu", "edisi": "Edisi 2"},
    "MKDU4225": {"kode": "MKDU4225", "nama": "Pendidikan Agama Buddha", "edisi": "Edisi 2"},
    "MKDU4226": {"kode": "MKDU4226", "nama": "Pendidikan Agama Khonghucu", "edisi": "Edisi 2"},
    "MKWU4108": {"kode": "MKWU4108", "nama": "Bahasa Indonesia", "edisi": "Edisi 1"},
    "MKWU4109": {"kode": "MKWU4109", "nama": "Pendidikan Kewarganegaraan", "edisi": "Edisi 1"},
    "MKWU4101": {"kode": "MKWU4101", "nama": "Pendidikan Agama Islam", "edisi": "Edisi 1"},
}


def get_catalog() -> Dict[str, Dict[str, str]]:
    """Memuat katalog mata kuliah UT ke memori sekali saja."""
    global _CATALOG_CACHE
    if _CATALOG_CACHE is not None:
        return _CATALOG_CACHE

    base_dir = Path(__file__).resolve().parent.parent
    catalog_path = base_dir / "data" / "ut_catalog.json"

    data = {}
    if catalog_path.exists():
        try:
            with open(catalog_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}

    # Gabungkan alias mata kuliah umum dasar
    for code, item in COMMON_ALIASES.items():
        if code not in data:
            data[code] = item

    _CATALOG_CACHE = data
    return _CATALOG_CACHE



def normalize_code(raw: str) -> str:
    """Menghapus spasi dan tanda hubung, konversi ke huruf kapital."""
    return re.sub(r"[^A-Za-z0-9]", "", raw).upper()


def lookup_ut_course(query: str, limit: int = 5) -> Dict[str, Any]:
    """
    Mendeteksi kode atau nama mata kuliah UT dari teks input pengguna.
    Mengembalikan data resmi kode, nama mata kuliah, dan edisi modul.
    """
    if not query or len(query.strip()) < 2:
        return {
            "found": False,
            "exact": False,
            "course": None,
            "suggestions": []
        }

    catalog = get_catalog()
    raw_query = query.strip()
    norm_query = normalize_code(raw_query)

    # 1. Cek apakah ada pola kode MK seperti FSSI4106, EKMA 4116, dsb
    code_pattern = re.search(r"([A-Za-z]{3,4})\s*[-]?\s*(\d{4})", raw_query)
    if code_pattern:
        extracted_code = f"{code_pattern.group(1)}{code_pattern.group(2)}".upper()
        if extracted_code in catalog:
            item = catalog[extracted_code]
            return {
                "found": True,
                "exact": True,
                "course": {
                    "kode": item["kode"],
                    "nama": item["nama"],
                    "edisi": item.get("edisi", "Edisi 1"),
                    "formatted_title": f"{item['kode']} {item['nama']} ({item.get('edisi', 'Edisi 1')})"
                },
                "suggestions": []
            }

    # 2. Cek pencarian langsung dengan normalisasi kode murni
    if norm_query in catalog:
        item = catalog[norm_query]
        return {
            "found": True,
            "exact": True,
            "course": {
                "kode": item["kode"],
                "nama": item["nama"],
                "edisi": item.get("edisi", "Edisi 1"),
                "formatted_title": f"{item['kode']} {item['nama']} ({item.get('edisi', 'Edisi 1')})"
            },
            "suggestions": []
        }

    # 3. Pencarian parsial berdasarkan kode atau nama mata kuliah
    lower_query = raw_query.lower()
    matches: List[Dict[str, str]] = []

    for code, data in catalog.items():
        name_lower = data.get("nama", "").lower()
        if norm_query in code or lower_query in name_lower:
            matches.append({
                "kode": data["kode"],
                "nama": data["nama"],
                "edisi": data.get("edisi", "Edisi 1"),
                "formatted_title": f"{data['kode']} {data['nama']} ({data.get('edisi', 'Edisi 1')})"
            })
            if len(matches) >= limit:
                break

    if matches:
        return {
            "found": True,
            "exact": False,
            "course": matches[0],
            "suggestions": matches
        }

    return {
        "found": False,
        "exact": False,
        "course": None,
        "suggestions": []
    }
