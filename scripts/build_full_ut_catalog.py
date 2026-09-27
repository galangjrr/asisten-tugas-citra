import asyncio
import httpx
import re
import json
from pathlib import Path

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

PRODI_URLS = [
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/118/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/122/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/151/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/152/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/163/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/252/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/253/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/274/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/279/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/30/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/310/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/311/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/312/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/38/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/458/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/471/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/472/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/483/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/50/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/51/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/512/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/513/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/53/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/532/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/54/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/541/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/542/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/55/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/56/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/57/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/58/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/580/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/589/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/59/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/599/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/60/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/61/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/62/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/70/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/71/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/72/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/73/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/76/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/78/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/83/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/84/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/87/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/90/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/92/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/93/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/931/",
    "https://pustaka.ut.ac.id/lib/ruangbaca/prodi/941/"
]


def extract_json_array(html: str):
    """Mengekstrak array objek JSON mata kuliah dari skrip halaman prodi."""
    for m in re.finditer(r'\[\s*\{\s*"kode"\s*:', html):
        start = m.start()
        bracket_count = 0
        end = start
        for i in range(start, len(html)):
            if html[i] == '[':
                bracket_count += 1
            elif html[i] == ']':
                bracket_count -= 1
                if bracket_count == 0:
                    end = i + 1
                    break
        json_str = html[start:end]
        try:
            return json.loads(json_str)
        except Exception:
            continue
    return []


async def fetch_prodi(client: httpx.AsyncClient, url: str, sem: asyncio.Semaphore):
    async with sem:
        try:
            res = await client.get(url, headers=HEADERS, timeout=20.0)
            if res.status_code == 200:
                items = extract_json_array(res.text)
                return items
        except Exception as e:
            print(f"Gagal mengambil {url}: {e}")
        return []


async def main():
    print(f"Mulai mengambil data dari {len(PRODI_URLS)} program studi UT...")
    sem = asyncio.Semaphore(5)
    catalog: dict = {}

    # Muat data eksisting jika ada
    existing_file = Path("data/ut_catalog.json")
    if existing_file.exists():
        try:
            with open(existing_file, "r", encoding="utf-8") as f:
                catalog = json.load(f)
            print(f"Katalog awal berisi {len(catalog)} entri.")
        except Exception:
            catalog = {}

    async with httpx.AsyncClient(follow_redirects=True) as client:
        tasks = [fetch_prodi(client, url, sem) for url in PRODI_URLS]
        results = await asyncio.gather(*tasks)

    total_extracted = 0
    for items in results:
        for it in items:
            kode_ba = (it.get("kode") or "").strip().upper()
            kode_mk = (it.get("kode_mk") or "").strip().upper()
            nama = (it.get("nama") or it.get("mk_label") or "").strip()
            mk_label = (it.get("mk_label") or nama).strip()
            edisi = (it.get("edisi") or "").strip()
            if not edisi:
                edisi = "Edisi 1"

            # 1. Simpan berdasarkan kode mata kuliah (misal FSSI4206)
            if kode_mk:
                catalog[kode_mk] = {
                    "kode": kode_mk,
                    "kode_ba": kode_ba,
                    "nama": mk_label or nama,
                    "edisi": edisi
                }
                total_extracted += 1

            # 2. Simpan juga berdasarkan kode bahan ajar (misal FSSI4316)
            if kode_ba:
                if kode_ba not in catalog:
                    catalog[kode_ba] = {
                        "kode": kode_ba,
                        "kode_ba": kode_ba,
                        "nama": nama or mk_label,
                        "edisi": edisi
                    }
                total_extracted += 1

    print(f"Selesai! Total entri katalog setelah scraping: {len(catalog)} entri.")
    
    # Simpan kembali ke data/ut_catalog.json
    with open("data/ut_catalog.json", "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)

    print("Cek FSSI4206:", catalog.get("FSSI4206"))
    print("Cek FSSI4316:", catalog.get("FSSI4316"))
    print("Cek FSSI4106:", catalog.get("FSSI4106"))


if __name__ == "__main__":
    asyncio.run(main())
