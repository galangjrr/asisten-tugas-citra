import io
import os
import re
import json
import base64
import asyncio
import numpy as np
from PIL import Image
from google.genai import types
from tools.gemini_client import generate_with_fallback


def smart_crop_book_spread(image_bytes: bytes) -> bytes:
    """
    Mendeteksi lembar buku putih di tengah jendela pembaca digital (seperti Ruang Baca Virtual UT)
    dan memotong area konten naskah, membuang menu samping, bilah atas, dan strip thumbnail.
    Jika gambar bukan dari jendela pembaca, gambar asli dikembalikan apa adanya.
    """
    if not image_bytes or len(image_bytes) < 100:
        return image_bytes

    try:
        im = Image.open(io.BytesIO(image_bytes))
        w, h = im.size
        if w < 400 or h < 400:
            return image_bytes

        arr = np.array(im)
        if arr.ndim < 3 or arr.shape[2] < 3:
            return image_bytes

        # Cek kontras bagian tengah untuk memastikan ini tampilan buku di dalam bingkai gelap
        center_cols = arr[:, int(0.3 * w):int(0.7 * w), :3]
        lum_y = np.mean(center_cols, axis=(1, 2))

        # Harus ada bilah atas dan bawah yang gelap serta lembar tengah yang terang
        has_dark_top = np.any(lum_y[:int(0.25 * h)] < 100)
        has_dark_bottom = np.any(lum_y[int(0.75 * h):] < 100)
        mid_y = h // 2
        if not (has_dark_top and has_dark_bottom and lum_y[mid_y] > 170):
            return image_bytes

        # Telusuri batas vertikal lembar buku dari titik tengah
        is_page_y = lum_y > 170
        top_y = mid_y
        while top_y > 0 and is_page_y[top_y]:
            top_y -= 1
        bottom_y = mid_y
        while bottom_y < h - 1 and is_page_y[bottom_y]:
            bottom_y += 1

        if (bottom_y - top_y) < (0.3 * h):
            return image_bytes

        # Telusuri batas horizontal lembar buku
        center_rows = arr[top_y:bottom_y, :, :3]
        lum_x = np.mean(center_rows, axis=(0, 2))
        is_page_x = lum_x > 170
        mid_x = w // 2
        if not is_page_x[mid_x]:
            return image_bytes

        left_x = mid_x
        while left_x > 0 and is_page_x[left_x]:
            left_x -= 1
        right_x = mid_x
        while right_x < w - 1 and is_page_x[right_x]:
            right_x += 1

        book_w = right_x - left_x
        book_h = bottom_y - top_y
        if book_w < (0.3 * w):
            return image_bytes

        # Potong margin dalam untuk membuang running header, bayangan lipatan buku, dan navigasi
        crop_x1 = max(0, int(left_x + 0.03 * book_w))
        crop_x2 = min(w, int(right_x - 0.04 * book_w))
        crop_y1 = max(0, int(top_y + 0.06 * book_h))
        crop_y2 = min(h, int(bottom_y - 0.03 * book_h))

        if crop_x2 <= crop_x1 or crop_y2 <= crop_y1:
            return image_bytes

        cropped_im = im.crop((crop_x1, crop_y1, crop_x2, crop_y2))
        out = io.BytesIO()
        cropped_im.save(out, format="PNG")
        return out.getvalue()
    except Exception as e:
        print(f"Pendeteksian crop buku dilewati: {e}")
        return image_bytes


def strip_markdown(text: str) -> str:
    """Membuang tanda format markdown dari balasan OCR supaya teks terbaca seperti ketikan biasa.
    Tanda bintang atau garis bawah yang menempel ke kata atau angka, seperti 2*3 atau nama_file, tidak disentuh."""
    text = re.sub(r"^[ \t]*```[^\n]*\n?", "", text, flags=re.M)
    text = re.sub(r"^[ \t]*([-*_])(?:[ \t]*\1){2,}[ \t]*$", "", text, flags=re.M)
    text = re.sub(r"^[ \t]*#{1,6}[ \t]+", "", text, flags=re.M)
    text = re.sub(r"^[ \t]*>[ \t]?", "", text, flags=re.M)
    text = re.sub(r"^([ \t]*)[*+][ \t]+", r"\1- ", text, flags=re.M)
    for mark in (r"\*\*", "__", r"\*", "_"):
        text = re.sub(rf"(?<![\w*]){mark}(?=[^\s*_])(.+?)(?<=[^\s*_]){mark}(?![\w*])", r"\1", text)
    text = re.sub(r"`([^`\n]+)`", r"\1", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# Keterangan gambar seperti "Gambar 1.2 Struktur Kata" dan baris sumbernya tidak dipakai sebagai bahan bacaan.
# Kalimat isi seperti "Gambar 1.2 menunjukkan ..." tetap, karena kata setelah nomornya huruf kecil.
IMAGE_LINE = re.compile(
    r"^\[(?i:gambar|image|foto)[^\]]*\]$|^(?i:sumber|source)(?i:\s+gambar)?\s*:"
    r"|^(?i:gambar|figure|foto)\s+\d+(?:\.\d+)*\.?(?:\s+[A-Z][^.]*\.?)?$"
)
TABLE_DIVIDER = re.compile(r"^\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)*\|?$")
LIST_ITEM = re.compile(r"^(?:[-•]\s|\d{1,2}[.)]\s|\(\d{1,2}\)\s|[a-zA-Z][.)]\s)")
SENTENCE_END = (".", "?", "!", ":", ";")


def clean_ocr_text(text: str) -> str:
    """Merapikan hasil OCR satu lembar bacaan jadi teks rapat seperti ketikan manusia.
    Baris yang terpotong lebar halaman disambung, satu paragraf satu baris, tanpa baris kosong.
    Gambar, keterangan gambar, dan sumbernya dibuang. Tabel jadi satu baris per baris tabel dengan pemisah ' | '."""
    blocks = []
    joined = False
    for line in strip_markdown(text).split("\n"):
        line = re.sub(r"[ \t ]+", " ", line).strip()
        if not line or TABLE_DIVIDER.match(line) or IMAGE_LINE.match(line):
            continue
        if line.startswith("|") or line.endswith("|"):
            line = " | ".join(cell.strip() for cell in line.strip("|").split("|"))
        if not blocks or " | " in line or " | " in blocks[-1] or LIST_ITEM.match(line):
            blocks.append(line)
            joined = False
            continue
        prev = blocks[-1]
        # ponytail: judul ditebak dari baris pendek tanpa tanda baca akhir, baris isi yang kebetulan pendek bisa ikut terpisah
        is_heading = not joined and len(prev) < 60 and not prev.endswith(SENTENCE_END + (",",))
        new_paragraph = (prev.endswith(SENTENCE_END) and not line[0].islower()) or (
            line[0].isupper() and (is_heading or LIST_ITEM.match(prev))
        )
        if new_paragraph:
            blocks.append(line)
            joined = False
        elif re.search(r"[a-z]-$", prev) and line[0].islower():
            # Kata yang dipenggal di ujung baris disambung lagi tanpa tanda hubung
            blocks[-1] = prev[:-1] + line
            joined = True
        else:
            blocks[-1] = f"{prev} {line}"
            joined = True
    return "\n".join(blocks)


async def extract_text_from_image(image_bytes: bytes, mime_type: str = "image/png") -> str:
    """
    Mengekstrak teks materi dari gambar tangkapan layar modul kuliah.
    Mengabaikan watermark, teks header pembaca, dan menghasilkan teks bersih.
    """
    if not image_bytes or len(image_bytes) < 100:
        return ""

    image_bytes = smart_crop_book_spread(image_bytes)

    prompt = (
        "Kamu adalah sistem OCR akademis presisi tinggi. "
        "Tugasmu mengekstrak seluruh teks materi kuliah, paragraf pembahasan, "
        "poin penjelasan, atau daftar bahasan yang ada pada gambar tangkapan layar modul ini. "
        "Abaikan watermark pengguna atau hak cipta kampus seperti 'User: ... HAK CIPTA UT'. "
        "Abaikan tombol navigasi penampil seperti nomor halaman di luar teks materi. "
        "Kembalikan teks materi aslinya secara utuh, rapi, dan mudah dibaca tanpa komentar tambahan. "
        "Tulis sebagai teks polos tanpa format markdown: jangan pakai tanda ** atau * untuk tebal dan miring, "
        "tanda # untuk judul, garis --- pemisah, atau blok kode. Judul cukup ditulis di baris tersendiri, "
        "daftar poin cukup diawali tanda - atau nomor. Sambung baris yang terpotong lebar halaman "
        "sehingga satu paragraf ditulis utuh dalam satu baris, tanpa baris kosong di antaranya. "
        "Jangan tulis atau deskripsikan gambar, foto, diagram, dan bagan, termasuk keterangan dan sumbernya. "
        "Tulis tabel satu baris per baris tabel dengan pemisah ' | ', baris pertama berisi judul kolom."
    )

    try:
        response = await generate_with_fallback(
            "fast",
            [types.Part.from_bytes(data=image_bytes, mime_type=mime_type), prompt],
            config=types.GenerateContentConfig(temperature=0.1),
            timeout=15.0,
            total_budget=40.0,
        )
    except Exception as e:
        print(f"Vision OCR gagal: {e}")
        return ""

    return clean_ocr_text(response.text or "")


# Gambar di bawah ukuran ini biasanya ikon atau garis hiasan. Logo yang lebih besar disaring oleh balasan SKIP_IMAGE.
MIN_QUESTION_IMAGE_BYTES = 2 * 1024
SKIP_IMAGE = "ABAIKAN"

# Isi deskripsi dibedakan per jenis gambar, karena soal matematika butuh angka dan label persis, bukan suasana
IMAGE_CONTENT_GUIDE = (
    "Jika berisi rumus atau persamaan, salin persis dalam notasi teks linear seperti (x+1)/2, x^2, sqrt(x), "
    "integral dari 0 sampai 1 f(x) dx. Jika berisi grafik atau kurva, sebut judul, label dan skala sumbu, "
    "titik atau nilai penting, serta bentuk kurvanya. Jika berisi bangun geometri atau diagram, sebut setiap label titik, "
    "panjang sisi, besar sudut, tanda siku, dan hubungan antarbagian. "
    "Jika berisi graf, pohon, atau jaringan, tulis daftar semua simpul lalu telusuri setiap garis dari ujung ke ujung dan tulis "
    "SEMUA sisi satu per satu dalam format X-Y, termasuk loop X-X, sisi ganda, arah panah, dan bobot sisi. Garis yang hanya lewat "
    "di dekat simpul tanpa berhenti di titiknya bukan sisi ke simpul itu. Jika ada garis yang ujungnya ragu karena bertumpuk atau buram, "
    "jangan dimasukkan ke daftar sisi, tulis terpisah sebagai 'sisi tidak pasti: X-Y (kemungkinan X-Z)'. "
    "Jika berisi tabel, salin isinya per baris dengan pemisah ' | '. "
    # Panjang deskripsi foto ikut soal: soal yang menyuruh mendeskripsikan gambar butuh bahan detail, gambar pendukung cukup ringkas
    "Jika berupa foto atau ilustrasi dan soal meminta mendeskripsikan gambar atau tempat di dalamnya, tulis sekitar 150 sampai 250 kata "
    "yang bisa langsung jadi bahan tulisan: jenis tempat, warna dan material, cahaya, tata letak dari kiri ke kanan, perabot, benda khas, "
    "ada tidaknya orang, dan suasana. Jika gambar hanya pendukung soal, tulis ringkas 3 sampai 5 kalimat. Jangan mendaftar isi rak atau "
    "menghitung benda satu per satu kecuali ditanyakan soal. Tulisan dekorasi di foto seperti menu, merek, atau papan nama tidak disalin kecuali ditanyakan soal. "
    "Jika bangunan, tempat, atau landmark terkenal dikenali dengan jelas, sebut namanya, tetapi jangan mengidentifikasi siapa orang di dalam gambar. "
    "Salin teks di dalam gambar yang menjadi bahan soal, seperti label, angka, judul, atau keterangan, dan lewati tulisan dekorasi yang tidak terbaca jelas. Tulis hanya yang benar-benar terlihat, jangan menebak atau menghitung jawabannya."
)

# Pendeskripsi harus tahu apa yang ditanyakan, kalau tidak detail seperti jumlah atau tulisan bisa terlewat
QUESTION_FOCUS_RULE = (
    "Pastikan deskripsi memuat setiap detail yang ditanyakan atau diperintahkan soal terkait gambar, "
    "misalnya jumlah benda, warna, tulisan, posisi, atau bagian tertentu. Hitung benda satu per satu dengan teliti. "
    "Jika detail yang ditanyakan tidak terlihat jelas, tulis bahwa detail itu tidak terlihat jelas. "
    "Jangan menjawab soalnya, cukup sajikan fakta visualnya. Teks soal di sekitar gambar hanya konteks, jangan disalin ke deskripsi."
)

IMAGE_DESCRIPTION_RULE = (
    "Untuk setiap gambar, foto, ilustrasi, grafik, diagram, atau rumus berbentuk gambar yang menjadi bahan soal, "
    "tulis di posisinya satu blok '[Gambar: ...]' berisi deskripsi objektif. " + IMAGE_CONTENT_GUIDE +
    " " + QUESTION_FOCUS_RULE + " Abaikan logo kampus di kop."
)


def prepare_image(image_bytes: bytes, mime_type: str, low: int = 1500, high: int = 1536) -> tuple:
    """
    Menyiapkan gambar sebelum dikirim ke Gemini. Gambar kecil diperbesar supaya garis tipis dan label huruf terbaca,
    gambar besar diperkecil, lalu dikompres JPEG supaya banyak gambar muat dalam satu permintaan.
    Gambar yang gagal dibuka dikirim apa adanya.
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img.load()
        if img.mode in ("RGBA", "LA", "P"):
            # Latar transparan jadi hitam kalau langsung diubah ke RGB, jadi ditempel di atas latar putih
            img = img.convert("RGBA")
            background = Image.new("RGB", img.size, "white")
            background.paste(img, mask=img.getchannel("A"))
            img = background
        else:
            img = img.convert("RGB")
        longest = max(img.size)
        if longest < low or longest > high:
            scale = (low if longest < low else high) / longest
            img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
        out = io.BytesIO()
        img.save(out, "JPEG", quality=85)
        return out.getvalue(), "image/jpeg"
    except Exception:
        return image_bytes, mime_type


# Batas data inline Gemini sekitar 20MB per permintaan, disisakan ruang untuk prompt
MAX_PDF_OCR_BYTES = 18 * 1024 * 1024


FIGURE_MARKER = "[[GAMBAR]]"


async def extract_text_from_pdf(pdf_bytes: bytes, mark_figures: bool = False) -> str:
    """
    Mentranskripsi seluruh halaman PDF lembar soal, termasuk halaman hasil scan, lewat pembaca dokumen Gemini.
    Jika mark_figures aktif, posisi gambar soal hanya ditandai FIGURE_MARKER supaya gambarnya bisa dipotong dan dibaca terpisah.
    Mengembalikan string kosong jika berkas terlalu besar atau semua model gagal.
    """
    if not pdf_bytes or len(pdf_bytes) > MAX_PDF_OCR_BYTES:
        return ""

    figure_rule = (
        f"Di posisi setiap gambar bahan soal seperti foto, ilustrasi, graf, diagram, grafik, atau bangun geometri, "
        f"tulis penanda {FIGURE_MARKER} saja pada baris tersendiri tanpa deskripsi. Abaikan logo kampus di kop."
        if mark_figures else IMAGE_DESCRIPTION_RULE
    )
    prompt = (
        "Transkripsikan SELURUH teks dari semua halaman dokumen lembar tugas kuliah ini, dari halaman pertama sampai terakhir. "
        "Salin kata per kata sesuai urutan baca, jangan meringkas, menerjemahkan, atau memperbaiki isi. "
        "Pertahankan nomor soal, huruf pilihan, label pembicara dialog, dan judul bagian persis seperti di dokumen. "
        "Tulis setiap baris tabel dalam satu baris dengan pemisah ' | '. "
        "Tulis rumus dan persamaan dalam notasi teks linear yang jelas strukturnya, misalnya (x+1)/2, x^2, sqrt(x), a_n. "
        "Pakai simbol Unicode seperti χ, π, ≤, ∑, bukan perintah LaTeX seperti \\chi. "
        "Pisahkan paragraf dengan satu baris kosong. Jangan tambahkan komentar, penanda halaman, atau format markdown. "
        + figure_rule
    )

    try:
        response = await generate_with_fallback(
            "fast",
            [types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"), prompt],
            config=types.GenerateContentConfig(temperature=0.0),
            timeout=90.0,
            total_budget=150.0,
        )
    except Exception as e:
        print(f"OCR PDF gagal: {e}")
        return ""

    return response.text.strip()


FIGURE_BOX_SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "page": {"type": "INTEGER"},
            "box_2d": {"type": "ARRAY", "items": {"type": "INTEGER"}},
        },
        "required": ["page", "box_2d"],
    },
}


async def locate_figures(pages: list) -> list:
    """
    Mencari kotak letak gambar soal di semua halaman dalam satu panggilan, skala 0 sampai 1000.
    Mengembalikan satu list kotak per halaman, urut dari atas ke bawah.
    Gambar soal dipotong lalu dibaca terpisah karena garis tipis seperti sisi graf tidak terbaca akurat dari satu halaman penuh.
    """
    if not pages:
        return []
    prompt = (
        f"Ada {len(pages)} halaman lembar soal di atas, berurutan dari halaman 1. "
        "Temukan setiap gambar bahan soal di tiap halaman: foto, ilustrasi, graf, diagram, grafik, bangun geometri, atau rumus berbentuk gambar. "
        "Abaikan logo, kop, stempel, garis pemisah, dan blok teks biasa. Kotak harus mencakup seluruh gambar beserta label hurufnya. "
        "Urutkan sesuai urutan baca dari atas ke bawah. "
        'Balas JSON murni berupa list objek {"page": nomor halaman, "box_2d": [ymin, xmin, ymax, xmax]} dengan skala 0 sampai 1000 '
        "relatif terhadap halaman itu, atau [] jika tidak ada."
    )
    contents = []
    for page in pages:
        data, mime = prepare_image(page, "image/png")
        contents.append(types.Part.from_bytes(data=data, mime_type=mime))
    contents.append(prompt)
    try:
        response = await generate_with_fallback(
            "fast",
            contents,
            config=types.GenerateContentConfig(
                temperature=0.0,
                response_mime_type="application/json",
                # Tanpa skema, model kadang membungkus box_2d jadi list di dalam list sehingga kotaknya terbuang
                response_schema=FIGURE_BOX_SCHEMA,
            ),
            timeout=45.0,
            total_budget=90.0,
        )
        items = json.loads(response.text)
    except Exception as e:
        print(f"Pencarian gambar di halaman gagal: {e}")
        return [[] for _ in pages]

    boxes = [[] for _ in pages]
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        page, box = item.get("page"), item.get("box_2d")
        if not isinstance(page, int) or not 1 <= page <= len(pages):
            continue
        if isinstance(box, list) and len(box) == 4 and all(isinstance(v, (int, float)) for v in box):
            ymin, xmin, ymax, xmax = (max(0, min(1000, v)) for v in box)
            if ymax > ymin and xmax > xmin:
                boxes[page - 1].append((ymin, xmin, ymax, xmax))
    return boxes
