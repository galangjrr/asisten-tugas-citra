import os
from typing import List, Dict, Any
from pypdf import PdfReader


def extract_text_with_pages(pdf_path: str, max_pages: int = 15) -> List[Dict[str, Any]]:
    """Mengekstrak teks dari berkas PDF naskah beserta nomor halamannya."""
    if not pdf_path or not os.path.exists(pdf_path):
        return []

    pages_data: List[Dict[str, Any]] = []

    try:
        reader = PdfReader(pdf_path)
        total_pages = len(reader.pages)
        pages_to_read = min(total_pages, max_pages)

        for page_idx in range(pages_to_read):
            page = reader.pages[page_idx]
            extracted = page.extract_text()
            if extracted and len(extracted.strip()) > 50:
                pages_data.append({
                    "page_number": page_idx + 1,
                    "text": extracted.strip()
                })

    except Exception as e:
        print(f"Error parsing PDF {pdf_path}: {e}")
        return []

    return pages_data
