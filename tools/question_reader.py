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
from pypdf.generic import ContentStream
from tools.ocr_vision import FIGURE_MARKER, MIN_QUESTION_IMAGE_BYTES, describe_image, extract_text_from_pdf, locate_figures


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


def _text_around(text: str, marker: str, width: int = 1000) -> str:
    """Teks soal sebelum dan sesudah gambar. Perintah bisa di atas ('gambar di bawah') atau di bawah ('gambar di atas')."""
    pos = text.find(marker)
    if pos < 0:
        return ""
    window = text[max(0, pos - width):pos] + "[GAMBAR INI]" + text[pos + len(marker):pos + len(marker) + width]
    return re.sub(r"\[\[GAMBAR_\d+\]\]", "[gambar lain]", window)


async def read_docx_with_images(file_bytes: bytes) -> str:
    """Membaca DOCX lalu mengganti penanda gambar dengan deskripsi isinya agar soal bergambar bisa dijawab."""
    images: list = []
    text = read_docx_file(file_bytes, images)
    return await _fill_image_markers(text, images)


async def _fill_image_markers(text: str, images: list) -> str:
    """Mengganti penanda [[GAMBAR_n]] dengan deskripsi gambar ke-n, dibaca bersama teks soal di sekitarnya."""
    descriptions = await asyncio.gather(
        *(describe_image(blob, mime, _text_around(text, f"[[GAMBAR_{i}]]")) for i, (blob, mime) in enumerate(images))
    )
    for i, desc in enumerate(descriptions):
        text = text.replace(f"[[GAMBAR_{i}]]", f"[Gambar: {desc}]" if desc else "")
    return text


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


async def read_pdf_file(file_bytes: bytes) -> str:
    """
    Membaca teks PDF lembar tugas. Jika ada halaman hasil scan atau gambar soal, di halaman mana pun,
    seluruh PDF ditranskripsi Gemini beserta deskripsi gambarnya supaya urutan isi tetap utuh.
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
        return extracted

    ocr_text = await _transcribe_with_figures(file_bytes)
    # Transkripsi yang lebih pendek dari teks bawaan berarti OCR gagal sebagian, jadi teks bawaan dipakai
    if len(ocr_text) > len(extracted):
        return ocr_text
    return extracted


# ponytail: lembar soal biasanya beberapa halaman, PDF lebih panjang dibaca dari halaman penuh saja agar panggilan tidak membengkak
MAX_FIGURE_PAGES = 20


def _render_pages(file_bytes: bytes, scale: float = 2.5) -> list:
    pdf = pdfium.PdfDocument(file_bytes)
    try:
        if len(pdf) > MAX_FIGURE_PAGES:
            return []
        return [pdf[i].render(scale=scale).to_pil() for i in range(len(pdf))]
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
    boxes_per_page = await asyncio.gather(*(locate_figures(_png(page)) for page in pages))
    crops = []
    for page, boxes in zip(pages, boxes_per_page):
        w, h = page.size
        for ymin, xmin, ymax, xmax in boxes:
            pad = 8
            crop = page.crop((
                max(0, (xmin - pad) * w // 1000), max(0, (ymin - pad) * h // 1000),
                min(w, (xmax + pad) * w // 1000), min(h, (ymax + pad) * h // 1000),
            ))
            crops.append((_png(crop), "image/png"))
    return crops


async def _transcribe_with_figures(file_bytes: bytes) -> str:
    """
    Transkripsi PDF dengan gambar soal yang dipotong dan dibaca satu per satu.
    Membaca graf atau diagram dari satu halaman penuh sering salah, sedangkan potongan yang diperbesar terbaca akurat.
    """
    text = await extract_text_from_pdf(file_bytes, mark_figures=True)
    count = text.count(FIGURE_MARKER)
    if not count:
        return text
    crops = await _crop_pdf_figures(file_bytes)
    if len(crops) != count:
        # Urutan gambar tidak bisa dicocokkan dengan penanda, jadi gambar dideskripsikan dari halaman penuh
        print(f"Peringatan: {count} penanda gambar tetapi {len(crops)} potongan, beralih ke deskripsi halaman penuh")
        return await extract_text_from_pdf(file_bytes)
    for i in range(count):
        text = text.replace(FIGURE_MARKER, f"[[GAMBAR_{i}]]", 1)
    return await _fill_image_markers(text, crops)


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


def count_numbered_questions(topic: str) -> int:
    """Menghitung butir soal bernomor berurutan dari 1, misal '1. Translate...' atau 'Soal 2:'."""
    numbers = [
        int(m.group(1))
        for m in re.finditer(r'(?im)^\s*(?:soal|pertanyaan|question)?\s*(\d{1,2})\s*[.):]\s+\S', topic)
    ]
    # Nomor yang mulai lagi dari 1 berarti soal terdiri dari beberapa bagian, jumlah section tidak bisa dikunci
    if numbers.count(1) > 1:
        return 0
    count = 0
    while count + 1 in numbers:
        count += 1
    return count


WORD_LIMIT = r'\b(\d{2,5})(?:\s*[-–]\s*(\d{2,5}))?\s*(?:kata|words?)\b'
# Batas yang berlaku per butir, misal '150 kata per soal', '100 words for each question', 'tiap soal maksimal 200 kata'
ITEM_SCOPE = r'(?:per|untuk\s+(?:setiap|tiap|masing-masing)|setiap|tiap|masing-masing|for\s+each|each)\s+(?:soal|nomor|butir|pertanyaan|jawaban|questions?|items?|answers?)'
ITEM_WORD_LIMIT = re.compile(rf'(?i){WORD_LIMIT}\s*{ITEM_SCOPE}|{ITEM_SCOPE}\D{{0,30}}?{WORD_LIMIT}')


def extract_word_limit(text: str) -> Optional[int]:
    """Mencari batas kata seperti '300 words', 'maksimal 500 kata', atau '250-300 kata' (diambil angka terbesar)."""
    match = re.search(rf'(?i){WORD_LIMIT}', text)
    if not match:
        return None
    return int(match.group(2) or match.group(1))


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
    if items and not total and (len(items) > 1 or question_count == 1):
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
    raw_items = raw.get("item_word_limits")
    items = [as_int(v, 10, 5000) for v in raw_items] if isinstance(raw_items, list) and raw_items else []
    # Satu angka tidak valid membuat seluruh daftar diragukan, jadi dipakai tebakan pola
    items = items if items and all(items) and len(items) <= 50 else guess["item_word_limits"]
    total, items = resolve_word_limits(as_int(raw.get("word_limit"), 50, 10000), items, question_count)
    return {
        "question_count": question_count,
        "answer_type": answer_type or guess["answer_type"],
        "needs_citations": needs_citations if isinstance(needs_citations, bool) else guess["needs_citations"],
        "answer_language": language if language in ("id", "en") else guess["answer_language"],
        "word_limit": total or guess["word_limit"],
        "item_word_limits": items,
    }


async def structure_assignment_with_ai(raw_text: str) -> Optional[Dict[str, Any]]:
    """Memilah lembar tugas secara cerdas menggunakan Gemini."""
    if not os.getenv("GEMINI_API_KEY") or len(raw_text.strip()) < 40:
        return None

    prompt = """Analisis lembar tugas kuliah ini (bisa berbahasa Indonesia atau Inggris).
Tugasmu: Pisahkan struktur dokumen ini ke dalam format JSON yang bersih:
1. "question_topic": HANYA inti pertanyaan tugas, studi kasus, atau instruksi esai yang harus dikerjakan atau dijawab, beserta SELURUH teks bacaan, kasus, atau dialog yang dibutuhkan untuk menjawabnya. BUANG kop dokumen (fakultas, prodi, kode mata kuliah, tahun, skor maks), capaian pembelajaran, indikator, label judul seperti "Guidelines:", "Petunjuk:", "Rubrik:", "Remember!", "Purpose:", batas waktu atau sesi, dan kalimat sapaan. Salin butir soal beserta teks kasus, dialog, atau bacaan pendukungnya PERSIS kata per kata, jangan diringkas atau diterjemahkan. Jika butir soal merujuk gambar, sertakan blok "[Gambar: ...]" terkait secara utuh.
2. "guidelines": Seluruh capaian pembelajaran, indikator, petunjuk teknis, rubrik penilaian, kriteria dosen, ketentuan format, atau batasan kata yang harus dipatuhi saat menulis jawaban.
3. "course_code": Kode mata kuliah resmi jika ada (contoh: EKMA4116, FSSI4206), atau null.
4. "answer_spec": spesifikasi bentuk jawaban yang diminta dosen:
   - "question_count": jumlah butir soal utama yang harus dijawab, atau null jika berupa satu topik esai tanpa nomor atau jika soal terdiri dari beberapa bagian yang nomornya mulai lagi dari 1.
   - "answer_type": salah satu dari "terjemahan" (menerjemahkan teks), "jawaban_singkat" (isian, hitungan, benar salah, pemahaman bacaan, gagasan utama, atau jawaban pendek per butir, MESKIPUN soalnya bernomor), "esai" (satu esai mengalir), "makalah" (makalah berbab), "jawaban_bernomor" (uraian atau analisis panjang per nomor soal yang butuh beberapa paragraf), atau "uraian" (uraian analitis umum). Pilih "jawaban_singkat" bila jawaban tiap butir cukup satu sampai dua kalimat atau cukup diambil dari teks bacaan.
   - "needs_citations": true jika dosen meminta sitasi, referensi, atau daftar pustaka; false jika tugas jelas tidak butuh rujukan seperti terjemahan, hitungan, atau menjawab dari teks bacaan yang sudah disediakan; null jika tidak jelas.
   - "answer_language": "id" atau "en", yaitu bahasa yang harus dipakai untuk MENULIS JAWABAN. Untuk soal terjemahan, ini bahasa sasaran terjemahan, bukan bahasa teks soal. null jika tidak jelas.
   - "word_limit": batas kata untuk SELURUH jawaban jika tertulis sebagai batas total (jika rentang seperti 250-300 kata, isi angka terbesar), atau null. Jika dosen hanya menulis batas per soal, isi null.
   - "item_word_limits": daftar batas kata per butir soal sesuai urutan nomor, jika dosen menulis batas per soal. Contoh 'maksimal 150 kata per soal' untuk 3 soal menjadi [150, 150, 150], sedangkan 'Soal 1 (200 kata), Soal 2 (300 kata)' menjadi [200, 300]. Isi null jika tidak ada batas per soal.

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
    "item_word_limits": null
  }
}

Dokumen Tugas:
""" + raw_text[:12000]

    try:
        res = await generate_with_fallback(
            "fast",
            prompt,
            config={"response_mime_type": "application/json"},
            timeout=15.0,
            total_budget=40.0,
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

    return parsed


async def parse_question_document(file_bytes: bytes, filename: str) -> Dict[str, Any]:
    """Membaca berkas soal dosen (PDF, DOCX, TXT) secara utuh tanpa memotong isi."""
    fn_lower = filename.lower()
    text = ""
    file_type = "unknown"

    if fn_lower.endswith(".docx"):
        file_type = "docx"
        text = await read_docx_with_images(file_bytes)
    elif fn_lower.endswith(".pdf"):
        file_type = "pdf"
        text = await read_pdf_file(file_bytes)
    elif fn_lower.endswith(".txt"):
        file_type = "txt"
        text = file_bytes.decode("utf-8", errors="replace").strip()
    else:
        # Coba baca sebagai docx, jika gagal coba pdf
        try:
            text = await read_docx_with_images(file_bytes)
            file_type = "docx"
        except Exception:
            text = await read_pdf_file(file_bytes)
            file_type = "pdf"

    clean_text = strip_time_limit_lines(text).strip()
    detected_code = extract_course_code_from_text(clean_text)

    # Coba gunakan pemilah cerdas AI terlebih dahulu
    ai_res = await structure_assignment_with_ai(clean_text)
    if ai_res and ai_res.get("question_topic"):
        q_topic = str(ai_res.get("question_topic", "")).strip()
        questions = q_topic if len(q_topic) >= 10 else clean_text
        g_lines = str(ai_res.get("guidelines", "")).strip()
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

