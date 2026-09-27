import httpx
import re
import json
import os

def build_catalog():
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    url = 'https://pustaka.ut.ac.id/lib/ruangbaca/'
    print('Mengunduh katalog resmi dari pustaka.ut.ac.id/lib/ruangbaca/ ...')
    try:
        r = httpx.get(url, headers=headers, follow_redirects=True, timeout=25.0)
        pattern = re.compile(r'\{"kode":"([^"]+)","nama":"([^"]+)","edisi":"([^"]+)"')
        matches = pattern.findall(r.text)
        print(f'Ditemukan {len(matches)} data mata kuliah modul UT.')
        
        catalog = {}
        for code, name, edisi in matches:
            clean_code = code.strip().upper()
            catalog[clean_code] = {
                "kode": clean_code,
                "nama": name.strip(),
                "edisi": edisi.strip()
            }
        
        os.makedirs("data", exist_ok=True)
        out_file = os.path.join("data", "ut_catalog.json")
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(catalog, f, ensure_ascii=False, indent=2)
            
        print(f'Sukses menyimpan {len(catalog)} mata kuliah ke {out_file}!')
        print('Contoh FSSI4106:', catalog.get('FSSI4106'))
        print('Contoh EKMA4116:', catalog.get('EKMA4116'))
        print('Contoh MKDU4110:', catalog.get('MKDU4110'))
    except Exception as e:
        print('Gagal mengambil katalog:', e)

if __name__ == '__main__':
    build_catalog()
