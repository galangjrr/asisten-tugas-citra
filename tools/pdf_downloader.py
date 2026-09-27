import os
import httpx
from typing import Optional, Any, Union



STORAGE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "storage")


async def download_paper_pdf(pdf_candidates: Any, paper_id: str) -> Optional[str]:
    """Mengunduh berkas PDF naskah asli ke direktori penyimpanan lokal dan memvalidasi keasliannya."""
    if not pdf_candidates or not paper_id:
        return None

    if isinstance(pdf_candidates, str):
        urls = [pdf_candidates]
    elif isinstance(pdf_candidates, list):
        urls = pdf_candidates
    else:
        return None

    os.makedirs(STORAGE_DIR, exist_ok=True)
    safe_filename = f"{paper_id.replace(':', '_')}.pdf"
    destination_path = os.path.join(STORAGE_DIR, safe_filename)

    # Jika berkas sudah pernah diunduh dan valid, gunakan kembali
    if os.path.exists(destination_path) and os.path.getsize(destination_path) > 5000:
        return destination_path

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/pdf,application/octet-stream,*/*",
    }

    for url in urls:
        if not url or not (url.startswith("http://") or url.startswith("https://")):
            continue
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                response = await client.get(url, headers=headers)
                if response.status_code != 200:
                    continue

                content = response.content
                # Validasi berkas bukan halaman galat HTML atau teks kosong
                if len(content) < 5000:
                    continue

                # Validasi header penanda PDF
                if not content.startswith(b"%PDF"):
                    if b"<html" in content[:200].lower():
                        continue

                with open(destination_path, "wb") as f:
                    f.write(content)

                return destination_path

        except Exception as e:
            print(f"Percobaan unduh PDF dari {url} gagal: {e}")
            continue

    return None
