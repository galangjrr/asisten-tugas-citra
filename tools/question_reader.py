import io
import os
import json
import re
import asyncio
from typing import Dict, Any, Optional
import pypdf
import docx
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from docx.text.run import Run
from tools.gemini_client import generate_with_fallback
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
from pypdf.generic import ContentStream
from google.genai import types
from tools.ocr_vision import (
    FIGURE_MARKER, IMAGE_CONTENT_GUIDE, MIN_QUESTION_IMAGE_BYTES, QUESTION_FOCUS_RULE, SKIP_IMAGE,
    extract_text_from_pdf, locate_figures, prepare_image,
)


def extract_course_code_from_text(text: str) -> Optional[str]:
    """Mencari pola kode mata kuliah UT seperti EKMA4116 atau FSSI 4206 di lembar soal."""
    match = re.search(r'\b([A-Za-z]{4})\s*(\d{4})\b', text)
    if match:
        return f"{match.group(1).upper()}{match.group(2)}"
    return None


def _list_formats(doc) -> Dict[tuple, tuple]:
    """
    Memetakan (numId, ilvl) ke (format, angka awal) list Word, misal ('decimal', 6).
    Angka awal penting karena dosen sering melanjutkan nomor soal antar bagian, misal 1-5 lalu 6-10.
    """
    try:
        numbering = doc.part.numbering_part.element
    except Exception:
        return {}

    def int_val(el, default: int = 1) -> int:
        try:
            return int(el.get(qn("w:val")))
        except (AttributeError, TypeError, ValueError):
            return default

    abstract_levels: Dict[tuple, tuple] = {}
    for abstract in numbering.findall(qn("w:abstractNum")):
        abstract_id = abstract.get(qn("w:abstractNumId"))
        for lvl in abstract.findall(qn("w:lvl")):
            fmt = lvl.find(qn("w:numFmt"))
            fmt_val = fmt.get(qn("w:val")) if fmt is not None else "decimal"
            abstract_levels[(abstract_id, lvl.get(qn("w:ilvl")))] = (fmt_val, int_val(lvl.find(qn("w:start"))))

    formats: Dict[tuple, tuple] = {}
    for num in numbering.findall(qn("w:num")):
        num_id = num.get(qn("w:numId"))
        abstract_ref = num.find(qn("w:abstractNumId"))
        if abstract_ref is None:
            continue
        for (abstract_id, ilvl), level in abstract_levels.items():
            if abstract_id == abstract_ref.get(qn("w:val")):
                formats[(num_id, ilvl)] = level
        # startOverride di w:num mengalahkan angka awal bawaan abstractNum
        for override in num.findall(qn("w:lvlOverride")):
            start = override.find(qn("w:startOverride"))
            key = (num_id, override.get(qn("w:ilvl")))
            if start is not None and key in formats:
                formats[key] = (formats[key][0], int_val(start))
    return formats


def _list_marker(fmt: str, n: int) -> str:
    if fmt == "bullet":
        return "•"
    if fmt in ("lowerLetter", "upperLetter") and n <= 26:
        return f"{chr((96 if fmt == 'lowerLetter' else 64) + n)}."
    return f"{n}."


MATH_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"


def _group(text: str) -> str:
    """Bungkus dengan kurung bila lebih dari satu suku supaya pecahan dan pangkat tidak ambigu."""
    return text if len(text) <= 1 or text.isalnum() or text.startswith("(") and text.endswith(")") else f"({text})"


def omml_to_text(el) -> str:
    """Mengubah rumus Equation Word (OMML) ke notasi teks linear seperti (x+1)/2 atau x^2."""
    name = el.tag.replace(MATH_NS, "")
    if el.tag == f"{MATH_NS}t":
        return el.text or ""
    if not el.tag.startswith(MATH_NS) or name.endswith("Pr"):
        return ""

    def part(tag: str) -> str:
        child = el.find(f"{MATH_NS}{tag}")
        return "" if child is None else "".join(omml_to_text(c) for c in child)

    def prop(pr: str, key: str, default: str) -> str:
        node = el.find(f"{MATH_NS}{pr}/{MATH_NS}{key}")
        return default if node is None else node.get(f"{MATH_NS}val", "")

    if name == "f":
        return f"{_group(part('num'))}/{_group(part('den'))}"
    if name == "sSup":
        return f"{_group(part('e'))}^{_group(part('sup'))}"
    if name == "sSub":
        return f"{_group(part('e'))}_{_group(part('sub'))}"
    if name == "sSubSup":
        return f"{_group(part('e'))}_{_group(part('sub'))}^{_group(part('sup'))}"
    if name == "rad":
        deg = part("deg")
        return f"root({deg}, {part('e')})" if deg else f"sqrt({part('e')})"
    if name == "d":
        items = ["".join(omml_to_text(c) for c in e) for e in el.findall(f"{MATH_NS}e")]
        return prop("dPr", "begChr", "(") + prop("dPr", "sepChr", "|").join(items) + prop("dPr", "endChr", ")")
    if name == "nary":
        limits = "".join(f"_{_group(v)}" if tag == "sub" else f"^{_group(v)}" for tag, v in (("sub", part("sub")), ("sup", part("sup"))) if v)
        return f"{prop('naryPr', 'chr', '∫')}{limits} {part('e')}"
    if name == "func":
        return f"{part('fName')} {part('e')}"
    if name == "limLow":
        return f"{part('e')}_{_group(part('lim'))}"
    if name == "m":
        rows = [", ".join("".join(omml_to_text(c) for c in e) for e in mr.findall(f"{MATH_NS}e")) for mr in el.findall(f"{MATH_NS}mr")]
        return "[" + "; ".join(rows) + "]"
    return "".join(omml_to_text(c) for c in el)


def _paragraph_with_math(p_el, doc) -> str:
    """Teks paragraf beserta rumus Equation di posisinya, karena Paragraph.text membuang semua rumus."""
    if p_el.find(f".//{MATH_NS}oMath") is None:
        return Paragraph(p_el, doc).text
    paragraph = Paragraph(p_el, doc)
    parts = []
    for child in p_el.iterchildren():
        if child.tag in (f"{MATH_NS}oMath", f"{MATH_NS}oMathPara"):
            parts.append(omml_to_text(child))
        elif child.tag == qn("w:r"):
            parts.append(Run(child, paragraph).text)
        elif child.tag in (qn("w:hyperlink"), qn("w:ins"), qn("w:smartTag")):
            parts.extend(Run(r, paragraph).text for r in child.iter(qn("w:r")))
    return "".join(parts)


def read_docx_file(file_bytes: bytes, images: Optional[list] = None) -> str:
    """
    Membaca teks dokumen Word sesuai urutan aslinya, termasuk isi tabel.
    Nomor list otomatis Word dimunculkan lagi karena tidak tersimpan sebagai teks,
    padahal nomor itu yang membedakan butir soal dari bacaan.
    Jika list images diberikan, gambar soal dikumpulkan ke sana dan posisinya ditandai [[GAMBAR_n]].
    """
    doc = docx.Document(io.BytesIO(file_bytes))
    formats = _list_formats(doc)
    counters: Dict[tuple, int] = {}

    def image_markers(p_el) -> list:
        markers = []
        if images is None:
            return markers
        for blip in p_el.iter(qn("a:blip")):
            part = doc.part.related_parts.get(blip.get(qn("r:embed")))
            if part is None or len(part.blob) < MIN_QUESTION_IMAGE_BYTES:
                continue
            images.append((part.blob, part.content_type))
            markers.append(f"[[GAMBAR_{len(images) - 1}]]")
        return markers

    def paragraph_text(p_el) -> str:
        return " ".join(filter(None, [numbered_text(p_el), *image_markers(p_el)]))

    def numbered_text(p_el) -> str:
        text = _paragraph_with_math(p_el, doc).strip()
        # ponytail: hanya penomoran langsung di paragraf, penomoran yang diwariskan dari style heading belum dibaca
        num_pr = p_el.find(f"./{qn('w:pPr')}/{qn('w:numPr')}")
        if not text or num_pr is None:
            return text
        num_id = num_pr.find(qn("w:numId"))
        ilvl = num_pr.find(qn("w:ilvl"))
        key = (num_id.get(qn("w:val")) if num_id is not None else "0", ilvl.get(qn("w:val")) if ilvl is not None else "0")
        # numId 0 berarti penomoran sengaja dimatikan
        if key[0] == "0":
            return text
        fmt, start = formats.get(key, ("decimal", 1))
        counters[key] = counters.get(key, start - 1) + 1
        return f"{_list_marker(fmt, counters[key])} {text}"

    def table_lines(tbl) -> list:
        lines = []
        for tr in tbl.iterchildren(qn("w:tr")):
            cells = []
            for tc in tr.iterchildren(qn("w:tc")):
                cell = "\n".join(block_lines(tc)).strip()
                if cell and cell not in cells:
                    cells.append(cell)
            if cells:
                lines.append(" | ".join(cells))
        return lines

    def block_lines(parent) -> list:
        lines = []
        for child in parent.iterchildren():
            if child.tag == qn("w:p"):
                text = paragraph_text(child)
                if text:
                    lines.append(text)
            elif child.tag == qn("w:tbl"):
                lines.extend(table_lines(child))
        return lines

    return "\n\n".join(block_lines(doc.element.body))


IMAGE_MARKER = re.compile(r"\[\[GAMBAR_(\d+)\]\]")


def read_docx_with_images(file_bytes: bytes) -> tuple:
    """Membaca DOCX beserta gambar soalnya. Posisi gambar ke-n ditandai [[GAMBAR_n]] dan dideskripsikan saat strukturisasi."""
    images: list = []
    text = read_docx_file(file_bytes, images)
    return text, images


def fill_image_markers(text: str, descriptions: Dict[int, str]) -> str:
    """Mengganti penanda [[GAMBAR_n]] dengan deskripsi gambar ke-n. Gambar tanpa deskripsi, seperti logo, dihapus penandanya."""
    def describe(match):
        desc = descriptions.get(int(match.group(1)), "")
        return f"[Gambar: {desc}]" if desc else ""
    return IMAGE_MARKER.sub(describe, text)


# Font rumus LaTeX, Word, dan MathType. Teks bawaan pypdf merusak susunan pecahan dan pangkatnya.
MATH_FONT = re.compile(r"(?i)math|cmmi|cmsy|cmex|msbm|symbol|mt ?extra|stix")


def _has_math_font(page) -> bool:
    fonts = (page.get("/Resources") or {}).get("/Font") or {}
    return any(MATH_FONT.search(str(font.get_object().get("/BaseFont", ""))) for font in fonts.values())


def _drawing_ops(page) -> int:
    """Jumlah perintah garis dan kurva vektor. Graf atau bangun yang digambar dengan Shapes lalu diekspor ke PDF bukan gambar."""
    try:
        contents = page.get_contents()
        if contents is None:
            return 0
        ops = ContentStream(contents, page.pdf).operations
        return sum(1 for _, op in ops if op in (b"l", b"c", b"v", b"y"))
    except Exception:
        return 0


def _needs_vision(page, text: str) -> bool:
    """Halaman perlu dibaca Gemini bila hasil scan, memuat gambar soal, atau memuat rumus matematika."""
    try:
        images = page.images
        if len(text.strip()) < 30:
            return len(images) > 0
        # ponytail: ambang 4 garis atau kurva membedakan gambar dari garis pemisah kop, tabel Word biasanya digambar sebagai kotak
        return _has_math_font(page) or _drawing_ops(page) >= 4 or any(len(img.data) >= MIN_QUESTION_IMAGE_BYTES for img in images)
    except Exception:
        # Gambar yang tidak bisa diurai pypdf tetap dibaca Gemini agar isinya tidak hilang
        return True


async def read_pdf_file(file_bytes: bytes) -> tuple:
    """
    Membaca teks PDF lembar tugas beserta potongan gambar soalnya. Jika ada halaman hasil scan atau gambar soal,
    di halaman mana pun, seluruh PDF ditranskripsi Gemini supaya urutan isi tetap utuh.
    """
    reader = pypdf.PdfReader(io.BytesIO(file_bytes))
    page_texts = []
    needs_vision = False

    for page in reader.pages:
        t = (page.extract_text() or "").strip()
        if _needs_vision(page, t):
            needs_vision = True
        if t:
            page_texts.append(t)

    extracted = "\n\n".join(page_texts)
    if not needs_vision:
        return extracted, []

    ocr_text, crops = await _transcribe_with_figures(file_bytes)
    # Transkripsi yang lebih pendek dari teks bawaan berarti OCR gagal sebagian, jadi teks bawaan dipakai
    if len(ocr_text) > len(extracted):
        return ocr_text, crops
    return extracted, []


# ponytail: lembar soal biasanya beberapa halaman, PDF lebih panjang dibaca dari halaman penuh saja agar panggilan tidak membengkak
MAX_FIGURE_PAGES = 20
# Label seperti huruf simpul graf adalah objek teks kecil. Paragraf soal lebih besar dari ini dan tidak ikut digabung.
MAX_LABEL_POINTS = 40


def _object_boxes(page) -> tuple:
    """
    Kotak garis, gambar, dan label kecil di halaman, skala 0 sampai 1000 dari kiri atas seperti kotak dari Gemini.
    Objek selebar hampir satu halaman, misal hasil scan atau bingkai halaman, dilewati.
    Mengembalikan (garis dan gambar, label teks kecil).
    """
    width, height = page.get_size()
    kinds = (pdfium_c.FPDF_PAGEOBJ_PATH, pdfium_c.FPDF_PAGEOBJ_IMAGE, pdfium_c.FPDF_PAGEOBJ_TEXT)
    drawings, labels = [], []
    for obj in page.get_objects(filter=kinds):
        try:
            left, bottom, right, top = obj.get_bounds()
        except Exception:
            continue
        w, h = right - left, top - bottom
        if w * h > 0.5 * width * height:
            continue
        box = ((height - top) / height * 1000, left / width * 1000, (height - bottom) / height * 1000, right / width * 1000)
        if obj.type != pdfium_c.FPDF_PAGEOBJ_TEXT:
            drawings.append(box)
        elif w <= MAX_LABEL_POINTS and h <= MAX_LABEL_POINTS:
            labels.append(box)
    return drawings, labels


def _touches(a: tuple, b: tuple, gap: float) -> bool:
    return b[1] <= a[3] + gap and b[3] >= a[1] - gap and b[0] <= a[2] + gap and b[2] >= a[0] - gap


def _union(a: tuple, b: tuple) -> tuple:
    return min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])


def _expand_to_objects(box: tuple, drawings: list, labels: list, gap: float = 12) -> tuple:
    """
    Kotak dari Gemini sering memotong sebagian gambar. Kotak dilebarkan sampai mencakup semua garis dan label
    yang menyambung dengannya, karena posisi objek di PDF itu pasti. PDF hasil scan tidak punya objek ini, jadi kotaknya tetap.
    Hanya garis dan gambar yang boleh memperluas berantai. Label teks cuma ditambahkan sekali di akhir,
    supaya deretan teks pendek seperti pilihan jawaban tidak ikut tersambung sampai sehalaman.
    """
    remaining = list(drawings)
    grown = True
    while grown:
        grown = False
        for obj in list(remaining):
            if _touches(box, obj, gap):
                box = _union(box, obj)
                remaining.remove(obj)
                grown = True
    for label in [lb for lb in labels if _touches(box, lb, gap)]:
        box = _union(box, label)
    return box


def _render_pages(file_bytes: bytes, scale: float = 2.5) -> list:
    """Render tiap halaman beserta kotak objeknya."""
    pdf = pdfium.PdfDocument(file_bytes)
    try:
        if len(pdf) > MAX_FIGURE_PAGES:
            return []
        pages = []
        for i in range(len(pdf)):
            page = pdf[i]
            pages.append((page.render(scale=scale).to_pil(), _object_boxes(page)))
        return pages
    finally:
        pdf.close()


def _png(img) -> bytes:
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


async def _crop_pdf_figures(file_bytes: bytes) -> list:
    """Memotong setiap gambar soal dari halaman PDF sesuai urutan baca, dengan sedikit ruang agar label di tepi ikut."""
    try:
        pages = await asyncio.to_thread(_render_pages, file_bytes)
    except Exception as e:
        print(f"Render halaman PDF gagal: {e}")
        return []
    boxes_per_page = await locate_figures([_png(image) for image, _ in pages])
    crops = []
    for (image, objects), boxes in zip(pages, boxes_per_page):
        w, h = image.size
        for box in boxes:
            ymin, xmin, ymax, xmax = _expand_to_objects(box, *objects)
            pad = 8
            crop = image.crop((
                int(max(0, (xmin - pad) * w / 1000)), int(max(0, (ymin - pad) * h / 1000)),
                int(min(w, (xmax + pad) * w / 1000)), int(min(h, (ymax + pad) * h / 1000)),
            ))
            crops.append((_png(crop), "image/png"))
    return crops


async def _transcribe_with_figures(file_bytes: bytes) -> tuple:
    """
    Transkripsi PDF dengan gambar soal yang dipotong satu per satu, posisinya ditandai [[GAMBAR_n]].
    Membaca graf atau diagram dari satu halaman penuh sering salah, sedangkan potongan yang diperbesar terbaca akurat.
    """
    text = await extract_text_from_pdf(file_bytes, mark_figures=True)
    count = text.count(FIGURE_MARKER)
    if not count:
        return text, []
    crops = await _crop_pdf_figures(file_bytes)
    if len(crops) != count:
        # Urutan gambar tidak bisa dicocokkan dengan penanda, jadi gambar dideskripsikan dari halaman penuh
        print(f"Peringatan: {count} penanda gambar tetapi {len(crops)} potongan, beralih ke deskripsi halaman penuh")
        return await extract_text_from_pdf(file_bytes), []
    for i in range(count):
        text = text.replace(FIGURE_MARKER, f"[[GAMBAR_{i}]]", 1)
    return text, crops


# Judul bagian soal: "Soal:", "Soal 1:", "SOAL TUGAS TUTORIAL I", "Pertanyaan 2.", "Questions".
# Baris metadata seperti "Butir Soal No. : 1 dan 2" sengaja tidak cocok.
QUESTION_HEADING = re.compile(
    r'(?i)^(?:soal|pertanyaan|butir\s+soal|studi\s+kasus|kasus|questions?|tasks?)'
    r'(?:\s+(?:tugas|diskusi|latihan|ujian|tutorial|tuton|uas|uts)(?:\s+[\w.]+){0,3})?'
    r'(?:\s*\d+)?\s*(?::|$|[.)]\s)'
)

# Judul bagian petunjuk, kriteria, rubrik, atau capaian yang jadi catatan dosen.
GUIDELINE_HEADING = re.compile(
    r'(?i)^(?:petunjuk|kriteria|rubrik|ketentuan|tata\s+cara|pedoman|perhatian|catatan|'
    r'capaian\s+pembelajaran|indikator|tujuan|instruksi|instructions?|guidelines?|rubrics?|'
    r'criteria|notes?|remember|purpose|learning\s+outcomes?|format\s+(?:penulisan|jawaban)|'
    r'penilaian|scoring)\b[^:]{0,40}(?::|$)'
)

# Baris skor seperti "Total Score: 100" atau "Bobot 30%".
SCORE_LINE = re.compile(r'(?i)^(?:total\s+)?(?:skor|score|nilai|bobot)\b[^a-z]*\d+\s*%?$')

# Baris metadata kop soal seperti "Program Studi : Sastra Inggris".
META_LINE = re.compile(r'^[^:]{0,40}\s:\s|^:')

# Baris waktu pengerjaan seperti "Waktu : 30 menit" atau "Time allotted: 2 hours".
TIME_LIMIT_LINE = re.compile(
    r'(?im)^[ \t]*(?:waktu(?:\s+pengerjaan)?|alokasi\s+waktu|durasi|lama\s+pengerjaan|time(?:\s+(?:allotted|allowed|limit))?|duration)'
    r'[ \t]*[:：]?[ \t]*\d+[ \t]*(?:menit|jam|minutes?|mins?|hours?|hrs?)\b[^\n]*\n?'
)


def strip_time_limit_lines(text: str) -> str:
    """Membuang petunjuk waktu pengerjaan. Batas waktu ujian tidak boleh memengaruhi panjang atau isi jawaban."""
    return TIME_LIMIT_LINE.sub("", text)


def split_questions_and_guidelines(text: str) -> Dict[str, str]:
    """Memilah lembar tugas per bagian: kop dibuang, petunjuk ke guidelines, butir soal ke questions."""
    lines = [ln.strip() for ln in text.split("\n")]
    buckets: Dict[str, list] = {"header": [], "guide": [], "question": []}
    state = "header"
    found_question = False

    for ln in lines:
        if QUESTION_HEADING.match(ln):
            state = "question"
            found_question = True
        elif GUIDELINE_HEADING.match(ln):
            state = "guide"
        elif SCORE_LINE.match(ln):
            buckets["guide"].append(ln)
            continue
        buckets[state].append(ln)

    # Kop halaman yang berulang di tiap halaman PDF ikut terbuang dari soal
    header_lines = {ln for ln in buckets["header"] if ln}
    question_lines = [ln for ln in buckets["question"] if ln not in header_lines]

    # Paragraf panjang di kop, misal narasi studi kasus, tetap dianggap bagian soal
    header_prose = [
        ln for ln in buckets["header"]
        if len(ln) >= 60 and not META_LINE.search(ln)
    ]

    def join(parts: list) -> str:
        return re.sub(r'\n{3,}', "\n\n", "\n".join(parts)).strip()

    questions = join(header_prose + [""] + question_lines)
    guidelines = join([ln for ln in buckets["guide"] if ln not in header_lines])

    # Tanpa judul soal, batas soal dan petunjuk blok tidak bisa dipastikan, jadi teks dikembalikan utuh.
    # Pengecualiannya kriteria satu baris seperti "Indikator : ...", yang aman dipindah ke catatan dosen.
    if not found_question or len(questions) < 20:
        inline_guides = [ln for ln in lines if GUIDELINE_HEADING.match(ln) and re.search(r':\s*\S', ln)]
        kept = [ln for ln in lines if ln not in inline_guides]
        return {"questions": join(kept), "guidelines": join(list(dict.fromkeys(inline_guides)))}

    return {"questions": questions, "guidelines": guidelines}


ANSWER_TYPES = {"uraian", "terjemahan", "jawaban_singkat", "esai", "makalah", "jawaban_bernomor"}


ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"]


def _sequential_count(numbers: list) -> int:
    # Nomor yang mulai lagi dari 1 berarti soal terdiri dari beberapa bagian, jumlah section tidak bisa dikunci
    if numbers.count(1) > 1:
        return 0
    count = 0
    while count + 1 in numbers:
        count += 1
    return count


def count_numbered_questions(topic: str) -> int:
    """Menghitung butir soal bernomor berurutan dari 1, misal '1. Translate...', 'Soal 2:', atau 'a.' 'b.' tanpa angka."""
    numbers = [
        int(m.group(1))
        for m in re.finditer(r'(?im)^\s*(?:soal|pertanyaan|question)?\s*(\d{1,2})\s*[.):]\s+\S', topic)
    ]
    if numbers:
        return _sequential_count(numbers)
    # Romawi hanya huruf besar, karena 'i.' kecil bisa jadi butir huruf biasa
    romans = [ROMAN.index(m.group(1)) + 1 for m in re.finditer(r'(?m)^\s*(X|IX|IV|V?I{0,3})\s*[.)]\s+\S', topic) if m.group(1)]
    if romans:
        return _sequential_count(romans)
    # Huruf hanya dihitung jika tidak ada nomor angka, karena 'a. b.' di bawah nomor biasanya sub-soal
    letters = [ord(m.group(1).lower()) - 96 for m in re.finditer(r'(?m)^\s*([a-hA-H])\s*[.)]\s+\S', topic)]
    return _sequential_count(letters)


# Tanda soal eksakta. Satu istilah saja belum cukup, misal 'matriks' di esai ekonomi, jadi dihitung per istilah berbeda.
STEM_TERMS = re.compile(
    r'(?i)\b(?:big\s*o|O\(\s*n|kompleksitas|algoritma|algorithm|pseudocode|rekursif|recursive|sorting|stack|queue|'
    r'matriks|matrix|vektor|vector|determinan|determinant|invers|eigen\w*|gauss|jordan|cramer|'
    r'rata-rata|median|modus|varians|variance|standar\s+deviasi|standard\s+deviation|distribusi\s+normal|regresi|regression|'
    r'hipotesis|hypothesis|uji\s+[tz]|p-value|'
    r'coulomb|ampere|volt|ohm|farad|tesla|weber|henry|hukum\s+(?:gauss|faraday|ampere|ohm|kirchhoff)|'
    r'fluks\s+magnetik|medan\s+(?:listrik|magnet)|kapasitor|induktor|resistor|'
    r'persamaan\s+(?:linear|linier|kuadrat|diferensial)|equation|turunan|derivative|integral|peluang|probabilitas|probability|logaritma|'
    r'hitunglah|tentukan\s+nilai|calculate|compute)\b'
)
# Operasi angka seperti 3 + 4, x^2, atau 2 × 5. Rentang tahun seperti 2020-2021 sengaja tidak dihitung.
STEM_SYMBOLS = re.compile(r'\d\s*[+×*/÷^=]\s*\(?[\dA-Za-z]|[A-Za-z]\s*=\s*-?\d|[√∑∫∮≤≥μπΩλε²³]')


def is_stem_question(text: str) -> bool:
    """Soal hitungan eksakta: minimal dua istilah eksakta berbeda, atau satu istilah plus operasi angka."""
    terms = {m.group(0).lower() for m in STEM_TERMS.finditer(text or "")}
    has_symbols = bool(STEM_SYMBOLS.search(text or ""))
    return len(terms) >= 2 or (len(terms) >= 1 and has_symbols)


FORMAT_HEADING = re.compile(
    r'(?i)^(?:format|sistematika|struktur|susunan|kerangka|outline|structure)'
    r'(?:\s+(?:of\s+)?(?:penulisan|jawaban|tugas|makalah|esai|essay|laporan|naskah|tulisan|paper|answer|the\s+\w+))?'
    r'\s*(?::\s*(.*))?$'
)
# Judul dan daftar pustaka sudah dibuat terpisah oleh exporter, jadi tidak ikut jadi bagian isi
NOT_BODY_SECTION = re.compile(r'(?i)^(?:judul|title|daftar\s+pustaka|referensi|references?|bibliography|nama|nim)\b')


def _section_name(line: str) -> str:
    """'2. Pembahasan: berisi analisis' menjadi 'Pembahasan'."""
    name = re.sub(r'^\s*(?:[-•*·]|\(?[0-9a-zA-Z]{1,2}[.)])\s+', "", line)
    return re.split(r'\s*(?::|\s[-–]\s|\()', name, maxsplit=1)[0].strip()


def extract_required_sections(text: str) -> Optional[list]:
    """Mencari urutan bagian wajib dari dosen, misal 'Format Penulisan: Judul, Pendahuluan, Pembahasan, Kesimpulan'."""
    lines = [ln.strip() for ln in text.split("\n")]
    for index, line in enumerate(lines):
        match = FORMAT_HEADING.match(line)
        if not match:
            continue
        if match.group(1):
            names = [_section_name(part) for part in re.split(r'[,;.]|\s+dan\s+|\s+and\s+', match.group(1))]
        else:
            names = []
            for item in lines[index + 1:]:
                if not item:
                    if names:
                        break
                    continue
                name = _section_name(item)
                # Nama bagian itu pendek. Kalimat panjang berarti daftar sudah selesai.
                if len(name.split()) > 5:
                    break
                names.append(name)
        names = [n for n in names if n and not NOT_BODY_SECTION.match(n)]
        # Nama bagian tidak mengandung angka, jadi 'Times New Roman 12, spasi 1.5' bukan daftar bagian
        if 2 <= len(names) <= 12 and not any(re.search(r'\d', n) for n in names):
            return names
    return None


WORD_LIMIT = r'\b(\d{2,5})(?:\s*[-–]\s*(\d{2,5}))?\s*(?:kata|words?)\b'
# Batas yang berlaku per butir, misal '150 kata per soal', '100 words for each question', 'tiap soal maksimal 200 kata'
ITEM_SCOPE = r'(?:per|untuk\s+(?:setiap|tiap|masing-masing)|setiap|tiap|masing-masing|for\s+each|each)\s+(?:soal|nomor|butir|pertanyaan|jawaban|questions?|items?|answers?)'
ITEM_WORD_LIMIT = re.compile(rf'(?i){WORD_LIMIT}\s*{ITEM_SCOPE}|{ITEM_SCOPE}\D{{0,30}}?{WORD_LIMIT}')


# 'at least 200 words' itu batas bawah. Kalau dibaca sebagai batas atas, jawaban malah dipangkas di bawah minimal dosen.
MIN_WORDS_PREFIX = re.compile(r'(?i)(?:at\s+least|minimum|min\.?|minimal|paling\s+sedikit|sekurang-kurangnya|lebih\s+dari|more\s+than)\s*$')


def extract_word_limit(text: str) -> Optional[int]:
    """Mencari batas kata seperti '300 words', 'maksimal 500 kata', atau '250-300 kata' (diambil angka terbesar).
    Angka minimal tanpa rentang seperti 'at least 200 words' dilewati karena bukan batas atas."""
    for match in re.finditer(rf'(?i){WORD_LIMIT}', text):
        if not match.group(2) and MIN_WORDS_PREFIX.search(text[max(0, match.start() - 25):match.start()]):
            continue
        return int(match.group(2) or match.group(1))
    return None


def extract_item_word_limit(text: str) -> Optional[int]:
    """Mencari batas kata yang berlaku untuk tiap butir soal, bukan untuk seluruh jawaban."""
    match = ITEM_WORD_LIMIT.search(text)
    if not match:
        return None
    numbers = [g for g in match.groups() if g]
    return max(int(n) for n in numbers)


def resolve_word_limits(total: Optional[int], items: Optional[list], question_count: Optional[int]) -> tuple:
    """
    Menyatukan batas kata total dan per butir. Batas per butir yang seragam disebar ke semua butir,
    lalu totalnya dihitung sendiri jika dosen hanya menulis batas per soal.
    """
    if items and len(items) == 1 and question_count:
        items = items * question_count
    # Butir bernilai None tidak punya batas atas, jadi batas total ikut tidak berlaku.
    # Model sering mengisi total dari rentang satu soal, misal 250 dari '200-250 words' soal 2.
    if items and not all(items):
        return None, items
    if items and not total and all(items) and (len(items) > 1 or question_count == 1):
        total = sum(items)
    return total, items or None


def guess_answer_spec(questions: str, guidelines: str = "") -> Dict[str, Any]:
    """Menebak spesifikasi jawaban dengan pola teks, dipakai saat AI tidak tersedia."""
    combined = f"{questions}\n{guidelines}"
    count = count_numbered_questions(questions)

    # Cadangan saat AI tidak tersedia, jadi sengaja hanya menangkap sinyal yang khas.
    # Kata umum seperti 'bacaan' atau 'teks berikut' juga muncul di soal esai dan analisis.
    is_short_answer = re.search(
        r'(?i)\btrue\s*\(t\)|\btrue or false\b|\bbenar atau salah\b|\bmain idea\b|\bgagasan utama\b|\bfill in the blanks?\b|\bisilah titik',
        questions,
    )
    if re.search(r'(?i)\btranslat|\bterjemah', questions):
        answer_type = "terjemahan"
    elif re.search(r'(?i)\b(esai|essay)\b', questions):
        answer_type = "esai"
    elif re.search(r'(?i)\bmakalah\b|\bpaper\b|\bbab\s+i\b', questions):
        answer_type = "makalah"
    elif is_short_answer:
        answer_type = "jawaban_singkat"
    elif count:
        answer_type = "jawaban_bernomor"
    else:
        answer_type = None

    # Permintaan rujukan yang tertulis jelas selalu menang
    if re.search(r'(?i)sitasi|referensi|daftar\s+pustaka|rujukan|kutip|citation|references?\b|cite', combined):
        needs_citations = True
    elif answer_type in ("terjemahan", "jawaban_singkat"):
        needs_citations = False
    else:
        needs_citations = None

    language = None
    if re.search(r'(?i)into\s+indonesian|ke\s+(?:dalam\s+)?bahasa\s+indonesia', questions):
        language = "id"
    elif re.search(r'(?i)into\s+english|ke\s+(?:dalam\s+)?bahasa\s+inggris', questions):
        language = "en"

    # Angka pada frasa 'per soal' bukan batas total, jadi batas total hanya diambil jika tidak ada batas per butir
    item_limit = extract_item_word_limit(combined)
    total, items = resolve_word_limits(
        None if item_limit else extract_word_limit(combined),
        [item_limit] if item_limit else None,
        count,
    )
    return {
        "question_count": count or None,
        "answer_type": answer_type,
        "needs_citations": needs_citations,
        "answer_language": language,
        "word_limit": total,
        "item_word_limits": items,
        "required_sections": extract_required_sections(combined),
        "is_mathematical": answer_type not in ("esai", "makalah", "terjemahan") and is_stem_question(questions),
    }


def normalize_answer_spec(raw: Any, questions: str, guidelines: str = "") -> Dict[str, Any]:
    """Merapikan spesifikasi dari AI. Nilai yang tidak valid diganti tebakan pola, bukan dipercaya mentah."""
    guess = guess_answer_spec(questions, guidelines)
    if not isinstance(raw, dict):
        return guess

    def as_int(value: Any, low: int, high: int) -> Optional[int]:
        try:
            number = int(value)
        except (TypeError, ValueError):
            return None
        return number if low <= number <= high else None

    answer_type = raw.get("answer_type") if raw.get("answer_type") in ANSWER_TYPES else None
    language = raw.get("answer_language")
    needs_citations = raw.get("needs_citations")
    question_count = as_int(raw.get("question_count"), 1, 50) or guess["question_count"]
    # AI sering menghitung soal majemuk sebagai satu butir. Nomor eksplisit di teks soal lebih bisa dipercaya,
    # kecuali untuk esai atau makalah yang nomornya biasanya poin panduan satu tulisan.
    numbered = guess["question_count"] or 0
    if numbered >= 2 and (question_count or 0) < numbered and answer_type not in ("esai", "makalah"):
        question_count = numbered
        if answer_type in (None, "uraian"):
            answer_type = "jawaban_bernomor"
    raw_items = raw.get("item_word_limits")
    raw_items = raw_items if isinstance(raw_items, list) and any(v is not None for v in raw_items) else []
    # None berarti butir itu tanpa batas atas, misal dosen hanya menulis batas minimal
    items = [None if v is None else as_int(v, 10, 5000) for v in raw_items]
    # Satu angka tidak valid membuat seluruh daftar diragukan, jadi dipakai tebakan pola
    valid = items and len(items) <= 50 and all(n is not None for v, n in zip(raw_items, items) if v is not None)
    items = items if valid else guess["item_word_limits"]
    total, items = resolve_word_limits(as_int(raw.get("word_limit"), 50, 10000), items, question_count)
    sections = raw.get("required_sections")
    if isinstance(sections, list):
        sections = [_section_name(str(n)) for n in sections if n]
        sections = [n for n in sections if n and len(n) <= 60 and not NOT_BODY_SECTION.match(n)]
    # Pola teks lebih bisa dipercaya daripada AI yang kadang mengarang struktur dari rubrik
    sections = guess["required_sections"] or (sections if sections and 2 <= len(sections) <= 12 else None)
    return {
        "question_count": question_count,
        "answer_type": answer_type or guess["answer_type"],
        "needs_citations": needs_citations if isinstance(needs_citations, bool) else guess["needs_citations"],
        "answer_language": language if language in ("id", "en") else guess["answer_language"],
        "word_limit": total if items else (total or guess["word_limit"]),
        "item_word_limits": items,
        "required_sections": sections,
        "is_mathematical": (answer_type or guess["answer_type"]) not in ("esai", "makalah", "terjemahan") and is_stem_question(questions),
    }


# ponytail: batas total gambar per permintaan supaya payload inline di bawah 20MB, gambar sesudahnya tidak dideskripsikan
MAX_IMAGE_PAYLOAD = 14 * 1024 * 1024
MAX_STRUCTURE_CHARS = 12000


async def structure_assignment_with_ai(raw_text: str, images: list = ()) -> Optional[Dict[str, Any]]:
    """
    Memilah lembar tugas dan mendeskripsikan semua gambar soalnya dalam satu panggilan Gemini.
    images berisi (bytes, mime) untuk penanda [[GAMBAR_n]] ke-n. Deskripsinya dikembalikan di image_descriptions.
    """
    if not os.getenv("GEMINI_API_KEY") or len(raw_text.strip()) < 40:
        return None

    prompt = """Analisis lembar tugas kuliah ini (bisa berbahasa Indonesia atau Inggris).
Tugasmu: Pisahkan struktur dokumen ini ke dalam format JSON yang bersih:
1. "question_topic": HANYA inti pertanyaan tugas, studi kasus, atau instruksi esai yang harus dikerjakan atau dijawab, beserta SELURUH teks bacaan, kasus, atau dialog yang dibutuhkan untuk menjawabnya. BUANG kop dokumen (fakultas, prodi, kode mata kuliah, tahun, skor maks), capaian pembelajaran, indikator, label judul seperti "Guidelines:", "Petunjuk:", "Rubrik:", "Remember!", "Purpose:", batas waktu atau sesi, dan kalimat sapaan. Salin butir soal beserta teks kasus, dialog, atau bacaan pendukungnya PERSIS kata per kata, jangan diringkas atau diterjemahkan. Penanda gambar seperti [[GAMBAR_0]] wajib disalin persis di posisinya, jangan dihapus, diubah, atau diganti deskripsi.
   Seluruh nomor butir soal dan SELURUH anak kalimat pertanyaan di dalam satu butir wajib tetap di sini, termasuk permintaan kutipan atau bukti teks ('sertakan kutipan teks pendukung'), permintaan pendapat pribadi beserta alasannya ('sebutkan tokoh pilihanmu dan alasannya'), data, tabel, dan matriks soal. DILARANG memindahkan bagian pertanyaan apa pun ke guidelines atau memangkasnya.
2. "guidelines": HANYA keterangan administratif di luar materi yang dikerjakan: capaian pembelajaran, indikator, rubrik dan skor penilaian, batas waktu pengumpulan, ketentuan format (font, margin, spasi), batas jumlah kata, dan sapaan. Kalimat yang meminta mahasiswa menjawab, menganalisis, mengutip, atau memilih sesuatu adalah bagian soal, bukan guidelines.
3. "course_code": Kode mata kuliah resmi jika ada (contoh: EKMA4116, FSSI4206), atau null.
4. "answer_spec": spesifikasi bentuk jawaban yang diminta dosen:
   - "question_count": jumlah butir soal utama yang harus dijawab. Jika soal bernomor 1, 2, 3 atau Soal 1, Soal 2, isi sesuai jumlah nomor itu walau satu nomor berisi beberapa sub-pertanyaan. Isi null jika berupa satu topik esai tanpa nomor atau jika soal terdiri dari beberapa bagian yang nomornya mulai lagi dari 1.
   - "answer_type": salah satu dari "terjemahan" (menerjemahkan teks), "jawaban_singkat" (isian, hitungan, benar salah, pemahaman bacaan, gagasan utama, atau jawaban pendek per butir, MESKIPUN soalnya bernomor), "esai" (satu esai mengalir), "makalah" (makalah berbab), "jawaban_bernomor" (uraian atau analisis panjang per nomor soal yang butuh beberapa paragraf), atau "uraian" (uraian analitis umum). Pilih "jawaban_singkat" bila jawaban tiap butir cukup satu sampai dua kalimat atau cukup diambil dari teks bacaan.
   - "needs_citations": true jika dosen meminta sitasi, referensi, atau daftar pustaka; false jika tugas jelas tidak butuh rujukan seperti terjemahan, hitungan, atau menjawab dari teks bacaan yang sudah disediakan; null jika tidak jelas.
   - "answer_language": "id" atau "en", yaitu bahasa yang harus dipakai untuk MENULIS JAWABAN. Untuk soal terjemahan, ini bahasa sasaran terjemahan, bukan bahasa teks soal. null jika tidak jelas.
   - "word_limit": batas atas kata untuk SELURUH jawaban jika tertulis sebagai batas total (jika rentang seperti 250-300 kata, isi angka terbesar), atau null. Batas minimal seperti 'at least 300 words' bukan batas atas, isi null. Jika dosen hanya menulis batas per soal, isi null.
   - "item_word_limits": daftar batas kata per butir soal sesuai urutan nomor, jika dosen menulis batas per soal. Contoh 'maksimal 150 kata per soal' untuk 3 soal menjadi [150, 150, 150], sedangkan 'Soal 1 (200 kata), Soal 2 (300 kata)' menjadi [200, 300]. Batas minimal seperti 'at least 200 words' atau 'minimal 200 kata' BUKAN batas, jadi butir itu diisi null, misal 'Soal 1 at least 200 words, Soal 2 200-250 words' menjadi [null, 250]. Rentang seperti 200-250 memakai angka terbesar. Isi null untuk seluruh daftar jika tidak ada batas atas per soal.
   - "required_sections": daftar nama bagian yang WAJIB ada di jawaban sesuai urutan, jika dosen menulis format, sistematika, atau struktur penulisan. Contoh 'Format Penulisan: Judul, Pendahuluan, Pembahasan, Refleksi, Kesimpulan' menjadi ["Pendahuluan", "Pembahasan", "Refleksi", "Kesimpulan"]. Buang Judul dan Daftar Pustaka. Isi null jika dosen tidak menulis format bagian.

Format Keluaran (JSON murni):
{
  "question_topic": "...",
  "guidelines": "...",
  "course_code": null,
  "answer_spec": {
    "question_count": null,
    "answer_type": "uraian",
    "needs_citations": null,
    "answer_language": null,
    "word_limit": null,
    "item_word_limits": null,
    "required_sections": null
  }IMAGES_FORMAT
}
"""

    text = raw_text[:MAX_STRUCTURE_CHARS]
    image_parts: list = []
    used = 0
    for i, (blob, mime) in enumerate(images):
        if f"[[GAMBAR_{i}]]" not in text:
            continue
        data, mime = prepare_image(blob, mime)
        if used + len(data) > MAX_IMAGE_PAYLOAD:
            break
        used += len(data)
        image_parts += [f"Gambar untuk penanda [[GAMBAR_{i}]]:", types.Part.from_bytes(data=data, mime_type=mime)]

    images_rule = images_format = ""
    if image_parts:
        images_rule = (
            '5. "images": daftar deskripsi setiap gambar terlampir, berupa objek {"id": angka n dari penanda [[GAMBAR_n]], "description": "..."}. '
            "Deskripsikan isi gambar secara objektif dalam paragraf biasa tanpa format markdown. Data soal seperti rumus, grafik, graf, dan tabel ditulis lengkap. "
            + IMAGE_CONTENT_GUIDE + " Baca teks soal di sekitar penanda gambar itu untuk tahu detail apa yang ditanyakan. " + QUESTION_FOCUS_RULE
            + f" Jika gambar hanya logo, ikon, stempel, atau hiasan yang bukan bahan soal, isi description persis: {SKIP_IMAGE}.\n\n"
        )
        images_format = ',\n  "images": [{"id": 0, "description": "..."}]'
    prompt = prompt.replace("Format Keluaran (JSON murni):", images_rule + "Format Keluaran (JSON murni):", 1)
    prompt = prompt.replace("IMAGES_FORMAT", images_format, 1) + "\nDokumen Tugas:\n" + text

    try:
        res = await generate_with_fallback(
            "fast",
            [prompt, *image_parts],
            config={"response_mime_type": "application/json"},
            timeout=60.0 if image_parts else 15.0,
            total_budget=120.0 if image_parts else 40.0,
        )
        parsed = json.loads(res.text)
    except Exception as e:
        print(f"Peringatan: pemilah AI lembar tugas gagal, beralih ke pemilah pola: {e}")
        return None

    if isinstance(parsed, list) and parsed:
        parsed = parsed[0]
    if not isinstance(parsed, dict):
        return None

    # Jika guidelines berupa list, jadikan teks per baris
    g = parsed.get("guidelines")
    if isinstance(g, list):
        parsed["guidelines"] = "\n".join(str(item) for item in g)

    descriptions: Dict[int, str] = {}
    for item in parsed.get("images") or []:
        if not isinstance(item, dict):
            continue
        num = re.search(r"\d+", str(item.get("id", "")))
        desc = str(item.get("description") or "").strip()
        if num and desc and not desc.upper().startswith(SKIP_IMAGE):
            descriptions[int(num.group())] = desc
    parsed["image_descriptions"] = descriptions

    return parsed


async def parse_question_document(file_bytes: bytes, filename: str) -> Dict[str, Any]:
    """Membaca berkas soal dosen (PDF, DOCX, TXT) secara utuh tanpa memotong isi."""
    fn_lower = filename.lower()
    text = ""
    images: list = []
    file_type = "unknown"

    if fn_lower.endswith(".docx"):
        file_type = "docx"
        text, images = read_docx_with_images(file_bytes)
    elif fn_lower.endswith(".pdf"):
        file_type = "pdf"
        text, images = await read_pdf_file(file_bytes)
    elif fn_lower.endswith(".txt"):
        file_type = "txt"
        text = file_bytes.decode("utf-8", errors="replace").strip()
    else:
        # Coba baca sebagai docx, jika gagal coba pdf
        try:
            text, images = read_docx_with_images(file_bytes)
            file_type = "docx"
        except Exception:
            text, images = await read_pdf_file(file_bytes)
            file_type = "pdf"

    clean_text = strip_time_limit_lines(text).strip()
    detected_code = extract_course_code_from_text(clean_text)

    # Coba gunakan pemilah cerdas AI terlebih dahulu. Gambar soal ikut dideskripsikan di panggilan yang sama.
    ai_res = await structure_assignment_with_ai(clean_text, images)
    # Tanpa AI, penanda gambar dihapus karena tidak ada deskripsinya
    descriptions = (ai_res or {}).get("image_descriptions") or {}
    clean_text = fill_image_markers(clean_text, descriptions)
    if ai_res and ai_res.get("question_topic"):
        q_topic = fill_image_markers(str(ai_res.get("question_topic") or ""), descriptions).strip()
        questions = q_topic if len(q_topic) >= 10 else clean_text
        g_lines = fill_image_markers(str(ai_res.get("guidelines") or ""), descriptions).strip()
        c_code = ai_res.get("course_code") or detected_code
        spec = normalize_answer_spec(ai_res.get("answer_spec"), questions, g_lines)

        return {
            "success": True,
            "filename": filename,
            "file_type": file_type,
            "text": clean_text,
            "questions": questions,
            "detected_guidelines": g_lines,
            "char_count": len(clean_text),
            "detected_course_code": c_code,
            "word_count_hint": spec["word_limit"],
            "answer_spec": spec,
            "answer_spec_source": "ai",
        }

    # Fallback ke pemisah pola aturan regex jika AI tidak tersedia
    split_res = split_questions_and_guidelines(clean_text)
    questions = split_res.get("questions", clean_text)
    guidelines = split_res.get("guidelines", "")
    spec = guess_answer_spec(questions, guidelines)

    return {
        "success": bool(clean_text),
        "filename": filename,
        "file_type": file_type,
        "text": clean_text,
        "questions": questions,
        "detected_guidelines": guidelines,
        "char_count": len(clean_text),
        "detected_course_code": detected_code,
        "word_count_hint": spec["word_limit"],
        "answer_spec": spec,
        "answer_spec_source": "pola",
    }

