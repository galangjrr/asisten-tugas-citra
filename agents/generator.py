import json
import re
import asyncio
from typing import Any, Dict, List, Optional
from google.genai import types
from tools.gemini_client import generate_with_fallback
from tools.question_reader import count_numbered_questions, extract_required_sections, is_stem_question


def detect_language(topic: str, custom_instructions: str = "") -> str:
    """Mendeteksi apakah topik/instruksi tugas kuliah ditulis dalam bahasa Inggris atau Indonesia."""
    combined = f"{topic} {custom_instructions}".lower()
    english_words = {
        "the", "and", "is", "in", "to", "of", "that", "it", "with", "as", "for", "on",
        "was", "at", "by", "an", "be", "this", "which", "from", "write", "essay",
        "explain", "preference", "between", "living", "urban", "area", "metropolitan",
        "please", "discuss", "describe", "analyze", "compare", "contrast", "advantages",
        "disadvantages", "personal", "your", "assignment", "words", "course", "task",
        "paragraph", "argument", "arguments", "reflection", "short"
    }
    indonesian_words = {
        "dan", "yang", "di", "dari", "untuk", "ini", "itu", "dengan", "adalah", "pada",
        "ke", "dalam", "bisa", "atau", "oleh", "tugas", "jelaskan", "bagaimana", "analisis",
        "uraikan", "menurut", "modul", "apakah", "mengapa", "sebutkan", "berikan", "soal",
        "mahasiswa", "tuton", "materi", "penulisan", "makalah", "jawaban", "tulislah"
    }
    tokens = [w.strip(".,?!:;\"'()[]{}") for w in combined.split()]
    en_matches = sum(1 for w in tokens if w in english_words)
    id_matches = sum(1 for w in tokens if w in indonesian_words)
    if en_matches > id_matches:
        return "en"
    return "id"


# Soal yang meminta bukti teks verbatim, jadi kutipan langsung wajib walau aturan sitasi biasanya menyarankan parafrase
EVIDENCE_HINT = re.compile(
    r"(?i)\b(?:kutipan|kutip\w*|quotes?|quotations?|textual\s+evidence|bukti\s+teks\w*|bunyi\s+(?:teks|pasal)|salin\s+kalimat|pasal)\b"
)
# Tanda soal hitungan atau logika: operasi angka, simbol matematika, atau istilah matematika.
# Tanda hubung di antara angka sengaja tidak dihitung karena rentang tahun dan halaman seperti 2020-2021 sering muncul di esai.
REASONING_HINT = re.compile(
    r"\d\s*[+x×*/:÷^=]\s*\(?\d|\d\s*-\s*\(|[=√∑∫≤≥χπ]|\b(?:matriks|graf|persamaan|turunan|integral|limit|peluang|probabilitas|"
    r"boolean|k-map|logaritma|vektor|himpunan|kombinasi|permutasi|matrix|graph|equation|derivative|probability)\b",
    re.I,
)
IMAGE_BLOCK = re.compile(r"\[Gambar:[^\]]*\]\s*")
SUPERSCRIPT = str.maketrans("0123456789-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁻")


LATEX_SYMBOLS = {
    "times": "×", "cdot": "·", "div": "÷", "pm": "±", "leq": "≤", "le": "≤", "geq": "≥", "ge": "≥", "neq": "≠",
    "approx": "≈", "infty": "∞", "sum": "∑", "int": "∫", "oint": "∮", "pi": "π", "mu": "μ", "epsilon": "ε",
    "varepsilon": "ε", "lambda": "λ", "Omega": "Ω", "omega": "ω", "alpha": "α", "beta": "β", "theta": "θ",
    "sigma": "σ", "Delta": "Δ", "delta": "δ", "rightarrow": "→", "to": "→", "sqrt": "√",
}


def strip_latex(text: str) -> str:
    """Mengubah LaTeX mentah yang lolos dari model menjadi notasi teks biasa, karena Word dan PDF tidak merendernya."""
    if "\\" not in text and "$" not in text:
        return text

    # Baris matriks LaTeX dipisah \\ dan kolomnya &, diubah ke tabel pipa yang dibaca exporter
    def matrix_rows(m: re.Match) -> str:
        rows = [r.strip() for r in m.group(1).split("\\\\") if r.strip()]
        return "\n" + "\n".join(" | ".join(c.strip() for c in r.split("&")) for r in rows) + "\n"

    text = re.sub(r"\\begin\{[a-z]*matrix\}(.*?)\\end\{[a-z]*matrix\}", matrix_rows, text, flags=re.S)
    # ponytail: hanya pecahan dan akar tanpa kurung kurawal bersarang, sisanya cukup dibuang tandanya
    text = re.sub(r"\\[dt]?frac\{([^{}]*)\}\{([^{}]*)\}", r"(\1)/(\2)", text)
    text = re.sub(r"\\sqrt\{([^{}]*)\}", r"√(\1)", text)
    text = re.sub(r"\\(?:text|mathrm|mathbf)\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\(?:left|right)\b|\\[()\[\]]", "", text)
    text = re.sub(r"\\([A-Za-z]+)", lambda m: LATEX_SYMBOLS.get(m.group(1), m.group(1)), text)
    # Pembatas $ matematika dibuang, tapi $ sebelum angka tetap karena itu mata uang
    return re.sub(r"\$\$|\$(?! ?\d)", "", text)


def clean_output_text(text: str) -> str:
    """Merapikan keluaran model supaya terbaca seperti ketikan mahasiswa di Word.
    Em dash, en dash, dan elipsis satu karakter diganti tanda baca umum.
    Notasi linear seperti x^2 dan sqrt(100) diubah ke x² dan √100."""
    # Model kadang membalas dalam HTML. Pemisah paragraf jadi baris baru, tag format lain dibuang.
    # Hanya nama tag yang dikenal, supaya tanda < di rumus seperti x < 5 tidak ikut terhapus.
    text = re.sub(r"(?i)<br\s*/?>|</p>\s*<p[^>]*>", "\n", text)
    text = re.sub(r"(?i)</?(?:p|div|span|b|i|u|em|strong|h[1-6]|ul|ol|li)\b[^>]*>", "", text)
    text = re.sub(r"(?<=\d)[ \t]*[—–][ \t]*(?=\d)", "-", text)
    text = re.sub(r"^([ \t]*)[—–][ \t]*", r"\1- ", text, flags=re.M)
    text = re.sub(r"[ \t]*[—–][ \t]*", ", ", text)
    text = re.sub(r",\s*([.,;:?!])", r"\1", text)
    text = strip_latex(text)
    text = re.sub(r"\^\(?(-?\d+)\)?", lambda m: m.group(1).translate(SUPERSCRIPT), text)
    text = re.sub(r"\bsqrt\((\w+)\)", r"√\1", text)
    text = re.sub(r"\bsqrt\(", "√(", text)
    return text.replace("…", "...")


def robust_json_dict_parse(text: str) -> Optional[Dict[str, Any]]:
    """Mengekstrak dan mem-parse struktur kamus JSON dari respons model dengan berbagai strategi pemulihan."""
    if not text or not text.strip():
        return None

    raw = text.strip()

    # 1. Coba parse langsung
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return data[0]
    except Exception:
        pass

    # 2. Bersihkan blok markdown ```json ... ``` atau ``` ... ```
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return data[0]
    except Exception:
        pass

    # 3. Cari substring JSON terluar dengan kurung kurawal pertama dan terakhir
    first_brace = raw.find("{")
    last_brace = raw.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        snippet = raw[first_brace : last_brace + 1]
        try:
            data = json.loads(snippet)
            if isinstance(data, dict):
                return data
        except Exception:
            # 4. Tangani karakter kontrol liar, koma menggantung, dan string yang disambung gaya JavaScript
            #    seperti "1. Salah: " + "improving" yang kadang dikirim model cadangan
            try:
                sanitized = re.sub(r",\s*([\]}])", r"\1", snippet)
                sanitized = re.sub(r'"\s*\+\s*"', "", sanitized)
                sanitized = re.sub(r"(?<!\\)[\x00-\x1f]", lambda m: f"\\u{ord(m.group(0)):04x}", sanitized)
                data = json.loads(sanitized)
                if isinstance(data, dict):
                    return data
            except Exception:
                pass

    return None


# Aturan setia teks untuk analisis bacaan apa pun: cerpen, novel, drama, kasus hukum, atau artikel.
# Ditulis sebagai prinsip umum, bukan daftar contoh dari satu cerita, supaya berlaku untuk naskah mana saja.
TEXT_FIDELITY_RULES = """
    ATURAN SETIA PADA TEKS SUMBER (BERLAKU SAAT MENGANALISIS BACAAN, KASUS, ATAU DIALOG):
    - Bedakan suara narator dari suara tokoh. Kalimat di luar tanda petik dialog adalah narasi pengarang, jadi perkenalkan sebagai narasi, misal 'narator menggambarkan' atau 'pengarang menuliskan'. Frasa 'tokoh berkata', 'ia berkata pada dirinya sendiri', atau 'ia menyatakan' hanya boleh dipakai untuk kalimat yang di teks memang diucapkan atau dipikirkan tokoh itu.
    - Saat mengutip dialog, sebut pembicaranya sesuai teks. Jika teks tidak jelas siapa yang berbicara, jangan menebak nama pembicaranya.
    - Sebut tokoh dengan nama yang dipakai teks. Nama samaran, julukan, gelar, atau panggilan yang disebut teks sebagai nama palsu DILARANG digabung dengan nama asli menjadi nama lengkap baru. Jika tokoh punya nama samaran, sebut nama aslinya dan jelaskan samarannya sebagai samaran.
    - DILARANG menambah fakta tokoh yang tidak tertulis, seperti nama keluarga, umur, pekerjaan, hubungan, atau kejadian.
    - Jenis tindakan tokoh harus sama dengan teks. Pertanyaan tidak boleh ditulis sebagai tuntutan, permintaan sebagai perintah, dugaan sebagai kepastian, atau keinginan sebagai tindakan yang benar-benar terjadi.
    - Kata sifat untuk watak tokoh harus berdasar deskripsi atau tindakan di teks. Jika itu tafsiranmu, tandai sebagai tafsiran, misal 'terkesan' atau 'dapat dibaca sebagai'.
    - Angka, data, dan fakta yang tidak tertulis di teks soal atau bahan DILARANG ditulis seolah berasal dari teks, termasuk melanjutkan atau mengubah angka di teks, misal teks menyebut enam miliar lalu ditulis naik ke tujuh miliar. Ilustrasi tetap boleh asal jelas hanya permisalan.
"""

# Soal yang meminta menemukan dan membetulkan kesalahan di teks, data, atau pernyataan. Butuh kata kerja mencari atau
# membetulkan di dekat kata kesalahan, atau kalimat 'berisi N kesalahan', supaya esai tentang 'sampling error' tidak ikut.
ERROR_TASK = re.compile(
    r"(?i)\b(?:find|identify|spot|locate|correct|fix|temukan|carilah|cari|tunjukkan|identifikasi\w*|betulkan|perbaiki\w*|koreksi\w*)\b"
    r"[^.?!\n]{0,60}\b(?:mistakes?|errors?|kesalahan|keliru|yang\s+salah)\b"
    r"|\b(?:contains?|has|have|terdapat|ada|memuat)\s+(?:\w+\s+){0,2}(?:mistakes?|errors?|kesalahan)\b"
)
ERROR_TASK_RULES = """
    SOAL MENCARI DAN MEMBETULKAN KESALAHAN (MENGATUR SUSUNAN JAWABAN, NADA TETAP MENGIKUTI PROFIL GAYA):
    - Jumlah temuan WAJIB sama dengan jumlah kesalahan yang disebut soal. Pilih kesalahan yang jelas melanggar aturan tata bahasa, makna, hitungan, atau konsep, bukan pilihan kata yang sebenarnya masih benar.
    - Bahas per temuan dengan nomor 1, 2, dan seterusnya. Dalam kalimat biasa berbahasa keluaran naskah, tiap temuan menyebut bagian yang salah dikutip persis dari teks, perbaikannya, kalimat utuh yang sudah dibetulkan, lalu alasan yang menyebut aturan atau makna yang dilanggar.
    - Satu kalimat pengantar singkat boleh. DILARANG paragraf penutup yang hanya mengulang atau memuji perbaikan. Aturan paragraf penutup di profil gaya tidak berlaku untuk soal ini.
"""


def format_sources_text(papers: List[Dict[str, Any]]) -> str:
    """Isi naskah rujukan berlabel halaman. Dipakai saat menulis naskah dan saat menulis ulang satu bagian."""
    sources_text = ""
    for idx, p in enumerate(papers, 1):
        authors = ", ".join(p.get("authors", ["Anonim"]))
        year = p.get("year") or "n.d."
        title = p.get("title", "")
        pages_content = p.get("pages_content", [])
        if p.get("is_ut_bmp"):
            status_label = "Buku Materi Pokok (BMP) UT"
        elif p.get("is_manual_module"):
            status_label = "Bahan Bacaan dari Dosen"
        else:
            status_label = "Naskah Fisik PDF" if p.get("has_full_pdf") else "Abstrak Resmi Terverifikasi"

        sources_text += f"\n--- SUMBER {idx} [{status_label}] ---\n"
        sources_text += f"Judul: {title}\n"
        sources_text += f"Penulis: {authors}\n"
        sources_text += f"Tahun: {year}\n"
        sources_text += f"Publikasi: {p.get('venue') or 'Jurnal Ilmiah'}\n"
        sources_text += f"DOI: {p.get('doi') or '-'}\n"
        sources_text += "Isi Teks Berkas:\n"

        for page in pages_content:
            page_num = page.get("page_number", 1)
            # Bahan dosen dibaca utuh per bagian, naskah jurnal cukup cuplikan per halaman
            text_snippet = page.get("text", "")[:3000 if p.get("is_manual_module") else 1500]
            sources_text += f"[{page_num}]: {text_snippet}\n"
    return sources_text


# Sitasi dalam kurung yang menempel di tanda petik penutup, misal '"..." (Cather, 1896, hlm. 5)'
QUOTE_CITATION = re.compile(r'(["”])[ \t]*\((?=[^()]*(?:\b\d{4}\b|n\.d\.))[^()]*\)')


def strip_quote_citations(text: str) -> str:
    """Membuang sitasi kurung tepat setelah kutipan langsung. Sitasi parafrase di tengah kalimat tidak disentuh."""
    text = QUOTE_CITATION.sub(r"\1", text)
    # '...loves?".' jadi '...loves?"' karena kutipan sudah punya tanda baca penutup sendiri
    return re.sub(r'([?!.])(["”])\.', r"\1\2", text)


# Sitasi kurung di badan naskah, misal '(Prakosa, 2022)', '(Ruiz & Lee, 2021; Prakosa dkk., 2022, hlm. 5)'.
# Wajib ada koma sebelum tahun supaya kurung biasa seperti '(UU No. 13 Tahun 2003)' tidak ikut terbuang.
IN_TEXT_CITATION = re.compile(r"[ \t]?\((?:[A-Z][^()]*?,\s*(?:\d{4}[a-z]?|n\.d\.)(?:,\s*(?:hlm|p|pp|h)\.\s*[\d\-–, ]+)?;?\s*)+\)")


# Kata sambung penutup khas AI di awal kalimat. Model cadangan saat kuota padat tetap memakainya walau sudah dilarang di prompt.
CLICHE_OPENER = re.compile(r"(^|[.!?]\s+)(?:Pada akhirnya|Secara keseluruhan|Kesimpulannya|In conclusion|Ultimately|Overall),\s*(\w)", re.M)


def finalize_text(text: str, quote_citations: bool, citation_style: str = "in_text") -> str:
    """Menegakkan pilihan sitasi pengguna dan membuang pembuka kalimat klise pada teks keluaran model."""
    text = CLICHE_OPENER.sub(lambda m: m.group(1) + m.group(2).upper(), text)
    if citation_style == "list_only":
        return IN_TEXT_CITATION.sub("", text)
    return text if quote_citations else strip_quote_citations(text)


# Model cadangan sering menempelkan sapaan dan salam penutup surat ke paragraf, misal 'Dear Sarah, I hope...' dan '... soon. Warm regards, Citra.'
# Kata kuncinya wajib berhuruf kapital supaya kalimat biasa seperti 'I would love to, Citra' tidak ikut dipecah.
LETTER_GREETING = re.compile(r"^((?:Dear|Hi|Hello|Halo|Hai|Kepada|Untuk|Teruntuk)\b[^,\n.!?]{0,40},)[ \t]+(?=\S)")
LETTER_SIGNOFF = re.compile(
    r"[ \t]+((?:Warm(?:est)? regards|Best regards|Kind regards|Regards|Warmly|Sincerely|Your friend|"
    r"Salam hangat|Salam|Sahabatmu|Temanmu|Hormat saya)[^,\n.]{0,15},)[ \t]*([^\n]{1,40}?)\.?\s*$"
)


DIRECT_ANSWER_LABELS = {
    "terjemahan": "terjemahan teks",
    "jawaban_singkat": "jawaban singkat, isian, benar salah, pemahaman bacaan, atau hitungan",
}


# Konteks kampus dari layar sambutan. Kampus umum dilarang menyebut istilah UT supaya naskah tidak terbaca salah alamat.
TASK_TYPE_RULES = {
    "ut-diskusi": (
        "Tugas ini tanggapan forum diskusi Tutorial Online (Tuton) Universitas Terbuka. Tulis sebagai postingan diskusi mahasiswa "
        "yang langsung menanggapi pertanyaan inisiasi dengan sudut pandang sendiri yang didukung konsep, tanpa salam pembuka panjang dan tanpa judul bab."
    ),
    "ut-tugas": (
        "Tugas ini Tugas Tutorial Universitas Terbuka yang dinilai tutor per nomor soal. Jawab setiap nomor sampai tuntas sesuai perintahnya, "
        "dan jadikan modul BMP dasar konsep utama bila tersedia."
    ),
    "umum": (
        "Tugas ini tugas kuliah di kampus umum, bukan Universitas Terbuka. DILARANG menyebut Universitas Terbuka, UT, Tuton, BMP, "
        "atau tutor. Sebut pengajar sebagai dosen."
    ),
}


def task_type_rule(task_type: Optional[str]) -> str:
    rule = TASK_TYPE_RULES.get(task_type or "")
    return f"\n    KONTEKS KAMPUS:\n    - {rule}\n" if rule else ""


# Suara dasar semua gaya. Diturunkan dari prompt pendek yang terbukti menghasilkan jawaban paling alami:
# satu suara yang konsisten lebih ditaati model daripada banyak aturan yang saling tarik.
BASE_VOICE_RULES = """
    SUARA DASAR (BERLAKU UNTUK SEMUA GAYA):
    - Tulis sebagai mahasiswa sungguhan yang paham materinya, bukan ensiklopedia. Pakai kata sehari-hari yang lazim diketik mahasiswa, dan buat sebagian besar kalimat di bawah 25 kata.
    - Langsung masuk ke jawaban. Tanpa sapaan pembuka seperti 'Halo Tutor', 'Selamat pagi', atau 'Izin menjawab', dan tanpa penutup ringkasan seperti 'Demikian', 'Kesimpulannya', 'In conclusion', atau 'Semoga bermanfaat', kecuali profil gaya di bawah memintanya.
    - Paragraf pendek yang saling terhubung. Hindari daftar poin yang tiap barisnya diawali kata tebal. Heading bernomor polos hanya untuk memisahkan beberapa soal.
    - Beri alasan yang jelas dengan contoh sederhana yang membumi dan bisa dibayangkan.
    - DILARANG kata sok pintar khas AI: 'krusial', 'esensial', 'ranah', 'sinergi', 'menggarisbawahi', 'secara keseluruhan', 'penting untuk dicatat', 'dalam era modern ini', 'menatap masa depan', 'delve', 'crucial', 'multifaceted', 'pivotal', 'testament', 'tapestry', 'underscores', 'foster', 'beacon', 'it is important to note', 'in today's modern era'.
    - DILARANG ungkapan klise dan peribahasa basi: 'bagai pisau bermata dua', 'dua sisi mata uang', 'di era digital ini', 'tidak dapat dipungkiri', 'Semoga ke depannya', 'I hope this letter finds you well', 'time flies', 'a double-edged sword'. Tulis maksudnya langsung dengan kalimat biasa.
    - DILARANG frasa birokratis kosong: 'motor penggerak perekonomian', 'berjalan optimal', 'tantangan tersendiri', 'secara signifikan', 'memegang peranan penting', 'roda perekonomian', 'Pada akhirnya', 'menjadi kunci', 'derasnya arus'.
"""

# Profil per gaya. Contoh nada sengaja bertopik netral supaya model meniru suaranya, bukan isinya.
TONE_PROFILES = [
    {
        "keys": ("surat", "letter", "korespondensi"),
        "name": "SURAT PERSONAL",
        "rules": [
            "Tulis seperti orang yang mengirim surat ke teman atau kenalan: hangat, santai, tetap sopan, dengan kalimat sederhana.",
            "Sapaan pembuka dan salam penutup surat WAJIB ada, masing-masing di baris sendiri dengan \\n. Buka dengan sapaan yang memakai nama penerima dari soal, misalnya 'Dear Carmen,' atau 'Halo Rina,'. Jika soal tidak menyebut nama, pakai nama yang wajar. Tulis tanggal di baris pertama jika soal meminta format surat.",
            "Kalimat pertama setelah sapaan langsung masuk ke kabar atau kenangan yang konkret, misalnya 'It has been so long since we last saw each other.' DILARANG basa-basi template seperti 'I hope this letter finds you well' atau 'Semoga kamu sehat selalu'.",
            "Penuhi setiap poin isi yang diminta soal dengan detail pribadi yang konkret dan wajar, misalnya kegiatan, kejadian kecil, perasaan, atau rencana. Hindari kalimat umum yang bisa berlaku untuk siapa saja.",
            "Boleh bertanya balik ke penerima atau mengajak bertemu supaya terasa seperti percakapan.",
            "Tutup dengan salam pendek seperti 'Your friend,' atau 'Salam hangat,' lalu nama penulis sesuai aturan nama penulis.",
            "Surat bukan makalah. Jika mahasiswa memilih rujukan, sitasi tetap ditulis sesuai ATURAN SITASI di atas, tapi gagasannya diselipkan secara ringan sebagai sesuatu yang pernah kamu baca, tanpa istilah akademis yang kaku.",
        ],
        "example": (
            "Bulan lalu aku akhirnya ikut klub mendaki di kampus. Pendakian pertama ternyata lebih berat dari dugaanku, tiap sepuluh menit harus berhenti buat ambil napas. Tapi pemandangan dari puncak bikin capeknya hilang. Kamu masih suka bersepeda tiap Minggu pagi?",
            "I finally joined the campus hiking club last month. The first trip was harder than I expected, and I had to stop every ten minutes to catch my breath. Still, the view from the top made it worth it. Do you still go cycling on Sunday mornings?",
        ),
    },
    {
        "keys": ("reflektif", "opini", "reflective", "opinion"),
        "name": "OPINI REFLEKTIF",
        "rules": [
            "Tulis seperti mahasiswa yang berbagi pandangan di forum diskusi kelas: sopan, hangat, dan mengalir seperti menjelaskan ke teman sekelas, bukan seperti laporan resmi.",
            "Paragraf pertama langsung menyatakan sikap atau jawaban inti dengan kalimat sendiri. Variasikan cara menyatakan pendapat. Frasa seperti 'Menurut saya' atau 'In my view' paling banyak dipakai sekali di seluruh naskah, dan DILARANG membuka setiap paragraf dengan frasa pendapat.",
            "Hubungkan konsep dengan contoh yang spesifik, misalnya profesi, situasi, atau kejadian tertentu, lalu jelaskan kenapa contoh itu mendukung pendapatmu. Hindari contoh kabur seperti 'di lingkungan sekitar kita' atau 'banyak orang'.",
            "Paragraf sekitar 3 sampai 5 kalimat, campur kalimat pendek dan sedang. Tanpa sub-judul kecuali soal terdiri dari beberapa nomor.",
            "Paragraf terakhir menegaskan pendapatmu dengan kalimat biasa dan memberi satu saran atau harapan yang konkret, tanpa label penutup seperti 'Sikap akhir saya' atau 'Pada akhirnya'.",
        ],
        "example": (
            "Kerja jarak jauh cocok untuk pekerjaan yang hasilnya bisa diukur, tapi tidak untuk semua orang. Desainer grafis bisa menyelesaikan revisi logo dari rumah tanpa harus macet dua jam di jalan. Lain cerita dengan perawat atau teknisi mesin yang pekerjaannya menempel di lokasi. Jadi yang perlu dipikirkan bukan boleh atau tidak, tapi pekerjaan mana yang memang bisa dipindah.",
            "Remote work suits jobs with measurable output, but not every job. A graphic designer can finish logo revisions at home instead of sitting in traffic for two hours. It is a different story for nurses or machine technicians whose work is tied to a place. So the real question is not whether remote work is allowed, but which jobs can actually move.",
        ),
    },
    {
        "keys": ("formal",),
        "name": "AKADEMIS FORMAL LUGAS",
        "rules": [
            "Pakai bahasa baku dan kalimat efektif yang jernih, bukan berbelit. Hindari kata santai seperti 'banget', 'nggak', atau 'aku', dan kontraksi dalam bahasa Inggris.",
            "Pakai 'saya' hanya jika soal meminta pendapat.",
            "Kalimat pertama tiap paragraf memuat gagasan utamanya, lalu diikuti penjelasan dan bukti.",
            "Formal bukan berarti panjang. Satu kalimat satu gagasan.",
            "WAJIB ada paling sedikit satu ilustrasi konkret yang diawali 'misalnya' atau 'contohnya', menyebut pelaku, situasi, atau angka tertentu, seperti pemilik usaha katering yang menunda membeli oven baru karena cicilannya naik. Uraian yang seluruhnya umum tanpa ilustrasi dianggap gagal.",
        ],
        "example": (
            "Inflasi yang terkendali sebenarnya dibutuhkan dalam perekonomian. Kenaikan harga yang moderat mendorong produsen menambah produksi karena keuntungan yang diharapkan ikut naik. Masalah muncul ketika inflasi melampaui kenaikan pendapatan, sebab daya beli rumah tangga turun dan konsumsi melemah.",
            "Controlled inflation is actually needed in an economy. Moderate price increases encourage producers to expand output because expected profits rise as well. Problems begin when inflation outpaces income growth, since household purchasing power falls and consumption weakens.",
        ),
    },
    {
        "keys": ("kritis", "critical"),
        "name": "ANALISIS KRITIS TAJAM",
        "rules": [
            "Jangan hanya menjelaskan, tapi menimbang. Bandingkan paling sedikit dua sudut pandang, teori, atau kasus, lalu sebut kelebihan dan kelemahannya.",
            "Uji setiap klaim: kapan berlaku, untuk siapa, dan apa batasannya.",
            "Ambil sikap yang jelas beserta alasannya. Sikap boleh dinyatakan dengan 'saya'.",
        ],
        "example": (
            "Program makan siang gratis sering dinilai dari jumlah anak yang menerimanya, padahal angka itu belum menjawab apakah gizi mereka membaik. Pendukung program menunjuk angka kehadiran sekolah yang naik. Angka itu nyata, tetapi bisa juga dipengaruhi faktor lain seperti musim panen yang sudah selesai. Saya baru yakin program ini berhasil kalau tinggi dan berat badan siswa ikut membaik dalam satu sampai dua tahun.",
            "Free school lunch programs are often judged by how many children receive them, yet that number does not show whether their nutrition improved. Supporters point to rising school attendance. That figure is real, but it may also reflect other factors such as the end of the harvest season. I would only call the program a success if students' height and weight improve within one or two years.",
        ),
    },
    {
        "keys": ("eksploratif", "exploratory"),
        "name": "EKSPLORATIF MENGALIR",
        "rules": [
            "Tulis seperti esai bertutur yang menelusuri gagasan langkah demi langkah.",
            "Boleh dibuka dengan pertanyaan, pengamatan, atau situasi konkret, lalu dikembangkan pelan-pelan sampai menjawab soal.",
            "Perpindahan antarparagraf terasa alami, bukan daftar poin. 'Saya' boleh dipakai secukupnya.",
            "Nada bertutur bertahan sampai akhir. Paragraf tengah tetap memakai pengamatan atau contoh konkret, misalnya teman, kejadian, atau kebiasaan tertentu, bukan berubah jadi uraian umum.",
            "Tutup dengan pikiran yang masih terbuka, misalnya pertanyaan atau hal yang ingin kamu coba sendiri, bukan nasihat moral atau ringkasan.",
        ],
        "example": (
            "Waktu pertama kali naik KRL di jam sibuk, saya heran kenapa hampir tidak ada yang bicara. Semua orang menunduk ke layar ponsel. Dari situ saya mulai bertanya, apakah teknologi membuat kita lebih dekat atau justru membangun tembok kecil di sekitar masing-masing orang.",
            "The first time I took a crowded commuter train, I was surprised that almost nobody talked. Everyone was looking down at their phones. That made me wonder whether technology brings us closer or quietly builds a small wall around each of us.",
        ),
    },
]


def voice_rules(tone: str, is_en: bool) -> str:
    """Aturan gaya bahasa dari pilihan Tahap 1. Dipakai saat menulis naskah dan setiap kali naskah ditulis ulang supaya gayanya tidak bergeser."""
    tone_lower = (tone or "").lower()
    profile = next((p for p in TONE_PROFILES if any(k in tone_lower for k in p["keys"])), None)
    # Tugas lama tanpa pilihan gaya cukup memakai suara dasar
    if not profile:
        return BASE_VOICE_RULES
    rules = "\n".join(f"    - {rule}" for rule in profile["rules"])
    example = profile["example"][1 if is_en else 0]
    return f"""{BASE_VOICE_RULES}
    PROFIL GAYA {profile['name']} (PILIHAN MAHASISWA, MENENTUKAN SUARA TULISAN):
{rules}
    - Contoh nada di bawah hanya untuk ditiru suaranya: panjang kalimat, pilihan kata, dan kehangatannya. DILARANG menyalin isi, topik, atau kalimatnya.
    CONTOH NADA:
    "{example}"
"""


def revision_style_rules(tone: str, is_en: bool) -> str:
    """Revisi dan penyesuaian panjang memakai aturan gaya yang sama dengan naskah awal supaya suaranya tidak kembali ke gaya umum."""
    return f"""
    GAYA DAN IDENTITAS DARI PILIHAN MAHASISWA (WAJIB DIPERTAHANKAN):
    - Pertahankan gaya bahasa, sudut pandang, dan nada versi sekarang. DILARANG mengubahnya jadi lebih kaku, lebih santai, atau gaya lain, kecuali arahan revisi memintanya.
    - Aturan sapaan pembuka dan salam penutup di bawah hanya berlaku untuk bagian pertama dan terakhir naskah.
    - DILARANG menambah identitas mahasiswa seperti nama, NIM, atau mata kuliah yang tidak ada di versi sekarang.
    {voice_rules(tone, is_en)}"""


async def generate_academic_draft(
    topic: str,
    papers_with_content: List[Dict[str, Any]],
    format_type: str = "otomatis",
    target_words: int = 1000,
    paragraph_depth: str = "standar",
    tone: str = "akademis formal",
    custom_instructions: str = "",
    answer_spec: Optional[Dict[str, Any]] = None,
    student_name: str = "",
    course_name: str = "",
    quote_citations: bool = False,
    task_type: Optional[str] = None,
    citation_style: str = "in_text",
) -> Dict[str, Any]:
    """
    Menyusun naskah tugas berbasis fakta dan nomor halaman dari dokumen yang diunduh.
    quote_citations False berarti kutipan langsung cukup bertanda petik tanpa sitasi kurung setelahnya.
    """
    # Spesifikasi jawaban sudah dicek pengguna, jadi nilainya mengalahkan tebakan otomatis
    spec = answer_spec or {}
    answer_type = spec.get("answer_type")
    is_direct_answer = answer_type in DIRECT_ANSWER_LABELS
    # Soal eksakta ditulis sebagai langkah hitungan, bukan esai, kecuali dosen jelas meminta esai atau makalah
    is_math = answer_type not in ("esai", "makalah", "terjemahan") and (spec.get("is_mathematical") or is_stem_question(topic))
    # Bukti teks diminta eksplisit di soal, jadi kutipan langsung wajib muncul walau aturan sitasi biasanya menyarankan parafrase
    wants_quotes = bool(EVIDENCE_HINT.search(f"{topic} {custom_instructions}"))
    word_limit = spec.get("word_limit")
    word_min = spec.get("word_min")
    if word_limit:
        target_words = min(target_words, word_limit)
    # Batas dosen menentukan target. Rentangnya dipakai lagi setelah naskah jadi untuk menyesuaikan panjang.
    bounds = length_bounds(word_min, word_limit)
    if bounds:
        target_words = bounds["goal"]
    if format_type == "otomatis" and answer_type in ("esai", "makalah"):
        format_type = answer_type

    if spec.get("answer_language") in ("id", "en"):
        is_en = spec["answer_language"] == "en"
    else:
        is_en = detect_language(topic, custom_instructions) == "en"
    estimated_pages = max(1, round(target_words / 280))
    is_personal_letter = any(k in (tone or "").lower() for k in ["surat", "letter", "korespondensi"])

    if is_personal_letter and format_type == "otomatis":
        format_type = "esai"

    # Tentukan strategi seksi dan paragraf berdasarkan target kata agar tidak diringkas LLM
    if target_words <= 400:
        min_sections = 3
        words_per_sec = round(target_words / 3)
        paras_per_sec = "1 paragraf bernas dan kohesif (sekitar 80-120 kata)"
        section_req = f"Hasilkan 3 bagian naskah (pembuka/thesis, elaborasi argumen inti, dan sintesis penutup). Tiap bagian berisi 1 paragraf kohesif agar total keseluruhan pas di kisaran {target_words} kata."
    elif target_words <= 700:
        min_sections = 3
        words_per_sec = round(target_words / 3)
        paras_per_sec = "1 sampai 2 paragraf padat"
        section_req = f"Hasilkan 3 sampai 4 bagian naskah. Tiap bagian terdiri dari 1 sampai 2 paragraf padat (sekitar {words_per_sec} kata per bagian)."
    elif target_words <= 1200:
        min_sections = 4
        words_per_sec = round(target_words / 4)
        paras_per_sec = "2 sampai 3 paragraf komprehensif"
        section_req = "Hasilkan minimal 4 sampai 5 bagian naskah. Tiap bagian wajib terdiri dari minimal 2 sampai 3 paragraf komprehensif."
    elif target_words <= 2000:
        min_sections = 6
        words_per_sec = round(target_words / 6)
        paras_per_sec = "3 sampai 4 paragraf mendalam dengan komparasi data"
        section_req = "Hasilkan minimal 6 sampai 7 bagian atau sub-bab naskah. Tiap bagian wajib terdiri dari minimal 3 sampai 4 paragraf mendalam."
    else:  # 2000 - 5000 kata (misalnya 3000 kata)
        min_sections = max(8, min(12, round(target_words / 320)))
        words_per_sec = round(target_words / min_sections)
        paras_per_sec = "3 sampai 5 paragraf panjang, analitis, dan berbobot penuh"
        section_req = f"Hasilkan minimal {min_sections} bagian atau sub-bab naskah terperinci. Setiap bagian WAJIB terdiri dari minimal 3 sampai 5 paragraf panjang dan berbobot (sekitar {words_per_sec} kata per bagian). DILARANG MERINGKAS."

    # Soal bernomor menentukan jumlah bagian, bukan target kata, agar 2 soal tidak dipecah jadi 4 nomor
    # Jenis jawaban terisi berarti lembar soal sudah dideteksi dan dicek pengguna, jadi jumlah soal kosong dipercaya.
    # Hitung ulang pola teks akan membaca poin panduan satu tulisan, misal '1. definisi 2. contoh', sebagai beberapa soal.
    # Pola teks hanya dipakai untuk soal yang ditempel manual tanpa deteksi.
    question_count = spec.get("question_count") or (None if answer_type else count_numbered_questions(topic))
    # Lebih dari satu soal selalu dijawab per nomor, termasuk jika tiap soal berbentuk esai, supaya judul butir tidak dikosongkan format esai.
    # Satu soal di mode otomatis tidak perlu nomor, cukup ditulis sebagai satu tulisan utuh.
    if question_count and (format_type == "bernomor" or is_direct_answer or question_count > 1):
        format_type = "bernomor"
        min_sections = question_count
        words_per_sec = round(target_words / question_count)
        section_req = (
            f"Lembar soal memuat TEPAT {question_count} butir soal bernomor. Hasilkan TEPAT {question_count} bagian di array 'sections', "
            f"satu bagian per butir soal dengan heading '1. ...' sampai '{question_count}. ...' mengikuti urutan soal. "
            "Heading memuat nomor dan topik butirnya, misal '1. PERUBAHAN KARAKTER UTAMA' dan '2. ANALISIS TEMA UTAMA'. "
            "DILARANG menggabung dua nomor dalam satu bagian, melewatkan nomor mana pun, atau menambah bagian pendahuluan, penutup, kesimpulan, atau nomor lain di luar butir soal."
        )
        # Tanpa target per butir, model menjawab tiap nomor sependek mungkin dan total naskah jauh di bawah target
        if not is_direct_answer:
            section_req += (
                f" Panjang tiap butir rata-rata sekitar {words_per_sec} kata. Butir yang menanyakan lebih banyak hal boleh lebih panjang "
                "dan butir sederhana lebih pendek, asal total naskah tercapai."
            )

    # Format penulisan yang ditulis dosen, misal Pendahuluan, Pembahasan, Refleksi, Kesimpulan, mengalahkan semua format bawaan
    required_sections = None if is_direct_answer else (
        spec.get("required_sections") or extract_required_sections(f"{topic}\n{custom_instructions}")
    )
    if required_sections:
        numbered_note = (
            f" Bagian pembahasan wajib menjawab ke-{question_count} butir soal secara berurutan dengan menyebut nomornya."
            if question_count and question_count > 1 else ""
        )
        format_type = "wajib"
        min_sections = len(required_sections)
        words_per_sec = round(target_words / min_sections)
        section_req = (
            f"Dosen mewajibkan format penulisan ini. Hasilkan TEPAT {min_sections} bagian di array 'sections' dengan heading persis "
            f"berurutan: {', '.join(repr(n) for n in required_sections)}. DILARANG menambah, menggabung, menomori, atau mengganti nama bagian.{numbered_note}"
        )

    if paragraph_depth == "ringkas":
        depth_instruction = "Panjang tiap paragraf berkisar 3 sampai 4 kalimat yang padat, lugas, dan to the point." if not is_en else "Each paragraph should be 3 to 4 concise and focused sentences."
    elif paragraph_depth == "elaboratif":
        depth_instruction = "Panjang tiap paragraf berkisar 5 sampai 7 kalimat dengan analisis kritis mendalam, kaya pembuktian data, dan komparasi temuan riset." if not is_en else "Each paragraph should be 5 to 7 sentences with in-depth critical analysis and empirical evidence."
    else:
        depth_instruction = "Panjang tiap paragraf berkisar 4 sampai 6 kalimat dengan penjelasan yang seimbang dan kohesif." if not is_en else "Each paragraph should be 4 to 6 sentences with balanced and cohesive reasoning."

    # Rangkum daftar seluruh paper agar wajib disitir
    paper_summary_list = []
    for idx, p in enumerate(papers_with_content, 1):
        author_list = p.get("authors", ["Anonim"])
        author_str = ", ".join(author_list[:2]) + (" dkk." if len(author_list) > 2 else "")
        yr = p.get("year") or "n.d."
        status_info = "Naskah Fisik PDF" if p.get("has_full_pdf") else "Abstrak & Metadata Resmi"
        paper_summary_list.append(f"Sumber {idx}: {author_str} ({yr}) - '{p.get('title')}' [{status_info}]")

    summary_sources_text = "\n".join(paper_summary_list)

    # Siapkan instruksi format berdasarkan pilihan pengguna dan bahasa
    if format_type == "wajib":
        format_guideline = f"""
            {"FORMAT STRUCTURE: Required by the lecturer" if is_en else "STRUKTUR FORMAT: Wajib dari dosen"}
            - {section_req}
            - {"Format ini adalah aturan dosen yang wajib dipatuhi, bukan rubrik penilaian." if not is_en else "This structure is a mandatory lecturer rule, not a grading rubric."}
            - {"Setiap bagian berisi" if not is_en else "Each section contains"} {paras_per_sec}, {"total sekitar" if not is_en else "about"} {target_words} {"kata" if not is_en else "words in total"}.
            """
        json_example = json.dumps({
            "title": "...",
            "sections": [{"heading": name, "content": "..."} for name in required_sections],
            "evidence_log": [{"source_index": 1, "paper_title": "...", "author_year": "...", "page_ref": "...", "evidence_summary": "..."}],
        }, ensure_ascii=False, indent=2)
    elif format_type == "esai":
        if is_en:
            format_guideline = f"""
            FORMAT STRUCTURE: Pure Organic Flowing Essay (NO Artificial Subheadings)
            - This assignment requires a pure academic essay.
            - STRICTLY FORBIDDEN to create numbered headers or artificial subheadings such as '1. Introduction', '2. Body', '4. Concluding Synthesis', etc.
            - In the JSON response, the 'heading' key in EVERY section MUST be an empty string: "heading": "".
            - Divide the essay into {min_sections} logical sections representing sequential paragraphs: introduction and thesis statement, body arguments with cited empirical findings, and thoughtful conclusion.
            - Total word count should naturally reflect {target_words} words ({paras_per_sec}).
            """
            json_example = """
            {
              "title": "Urban Living versus Metropolitan Life: A Personal Reflection",
              "sections": [
                {"heading": "", "content": "Living in an urban environment presents an appealing balance between accessibility and quality of life..."},
                {"heading": "", "content": "Furthermore, while metropolitan centers offer greater employment opportunities, empirical findings indicate that urban environments support healthier routines (Author, Year)..."},
                {"heading": "", "content": "Ultimately, my personal preference leans toward urban living because it fosters meaningful community ties while maintaining necessary modern infrastructure..."}
              ],
              "evidence_log": [
                {"source_index": 1, "paper_title": "Paper Title", "author_year": "Author (Year)", "page_ref": "p. 14", "evidence_summary": "Core empirical data or insight utilized in the essay"}
              ]
            }
            """
        else:
            format_guideline = f"""
            STRUKTUR FORMAT: Esai Mengalir Alami (Tanpa Sub-judul Kaku)
            - Naskah ini adalah esai murni yang mengalir utuh dari paragraf ke paragraf.
            - DILARANG KERAS membuat sub-judul atau heading bernomor seperti '1. Pendahuluan', '2. Pembahasan', '4. Sintesis Penutup', atau sub-judul buatan lainnya.
            - Di dalam array sections JSON, nilai 'heading' di SETIAP bagian WAJIB DIKOSONGKAN: "heading": "".
            - Pecah naskah menjadi {min_sections} bagian logis (paragraf pembuka, elaborasi argumen dan rujukan riset, serta sintesis penutup) dengan "heading": "".
            - Setiap bagian berisi {paras_per_sec} dengan total panjang sekitar {target_words} kata.
            """
            json_example = """
            {
              "title": "Judul Esai Akademis yang Reflektif",
              "sections": [
                {"heading": "", "content": "Paragraf pembuka yang mengantarkan pokok permasalahan dan tesis gagasan..."},
                {"heading": "", "content": "Paragraf pembahasan mendalam yang mengulas temuan riset dan perbandingan data (Penulis, Tahun)..."},
                {"heading": "", "content": "Paragraf penutup yang merangkum sintesis gagasan dan pandangan akhir..."}
              ],
              "evidence_log": [
                {"source_index": 1, "paper_title": "Judul Paper", "author_year": "Nama (Tahun)", "page_ref": "hlm. 14", "evidence_summary": "Poin data atau temuan riset spesifik yang dipakai"}
              ]
            }
            """
    elif format_type == "otomatis":
        if is_en:
            format_guideline = f"""
            FORMAT STRUCTURE: Context-Adaptive Format
            - Carefully analyze the assignment prompt:
              * If the prompt asks for an essay (e.g., contains 'essay', 'explain your preference', personal reflection, or open discussion without numbered question items):
                Write a pure organic flowing essay. For EVERY section in the sections array, the 'heading' key MUST be an empty string: "heading": "". DO NOT invent robotic headings like '1. Introduction' or '4. Concluding Synthesis'.
              * If the prompt consists of explicit numbered questions (e.g., '1.', '2.', 'Question 1'):
                Structure the output as numbered answers: '1. [Clear Question/Topic Heading]', '2. [Clear Question/Topic Heading]'.
              * If the prompt explicitly asks for a formal full-length paper or report (word count >= 1200 with formal chapters):
                Use standard academic paper structure: CHAPTER I INTRODUCTION, CHAPTER II DISCUSSION, CHAPTER III CONCLUSION.
            - Target length: approx {target_words} words ({paras_per_sec} per section).
            """
            json_example = """
            {
              "title": "Urban Living versus Metropolitan Life: An Evaluative Essay",
              "sections": [
                {"heading": "", "content": "First paragraph introducing the context and personal stance..."},
                {"heading": "", "content": "Subsequent paragraphs examining evidence, comparisons, and cited sources (Author, Year)..."},
                {"heading": "", "content": "Final paragraph synthesizing the core arguments and conclusion..."}
              ],
              "evidence_log": [
                {"source_index": 1, "paper_title": "Paper Title", "author_year": "Author (Year)", "page_ref": "p. 14", "evidence_summary": "Empirical finding utilized in the text"}
              ]
            }
            """
        else:
            format_guideline = f"""
            STRUKTUR FORMAT: Penyesuaian Otomatis Mengikuti Karakter Tugas
            - Analisis karakteristik soal atau tugas secara adaptif:
              * Jika tugas meminta esai (terdapat kata 'esai', 'essay', 'opini', 'pandangan pribadi', 'ceritakan', atau topik bebas tanpa butir soal bernomor):
                Susun sebagai Esai Mengalir Alami. Kosongkan nilai 'heading' di SETIAP bagian: "heading": "". DILARANG MEMBUAT sub-judul kaku artifisial seperti '1. Kontekstualisasi' atau '4. Sintesis Penutup'.
              * Jika lembar soal memuat butir pertanyaan bernomor eksplisit (misal: '1.', '2.', 'Soal 1', 'Pertanyaan A'):
                Susun sebagai Jawaban Bernomor terstruktur: '1. [Ringkasan Soal/Topik 1]', '2. [Ringkasan Soal/Topik 2]'.
              * Jika tugas meminta makalah formal lengkap (target kata >= 1200 atau meminta bab):
                Gunakan struktur baku: BAB I PENDAHULUAN, BAB II PEMBAHASAN, BAB III PENUTUP.
            - Target panjang: sekitar {target_words} kata ({paras_per_sec} per bagian).
            """
            json_example = """
            {
              "title": "Judul Naskah Akademis yang Tepat",
              "sections": [
                {"heading": "", "content": "Paragraf pembuka yang menguraikan konteks dan tesis utama..."},
                {"heading": "", "content": "Paragraf pembahasan mendalam yang membedah argumen dan bukti ilmiah (Penulis, Tahun)..."},
                {"heading": "", "content": "Paragraf penutup yang menyimpulkan pokok pikiran..."}
              ],
              "evidence_log": [
                {"source_index": 1, "paper_title": "Judul Paper", "author_year": "Nama (Tahun)", "page_ref": "hlm. 14", "evidence_summary": "Poin data atau temuan riset spesifik yang dipakai"}
              ]
            }
            """
    elif format_type == "mengalir":
        if is_en:
            format_guideline = f"""
            FORMAT STRUCTURE: Flowing Thematic Academic Discussion
            - Do not use rigid chapter divisions like CHAPTER I, CHAPTER II.
            - Divide the paper into at least {min_sections} dynamic thematic discussion headings.
            - Each thematic section must contain {paras_per_sec}.
            """
            json_example = """
            {
              "title": "Comprehensive Academic Discussion",
              "sections": [
                {"heading": "1. Context and Foundational Concepts", "content": "Paragraph 1...\\n\\nParagraph 2..."},
                {"heading": "2. Empirical Examination and Comparative Analysis", "content": "Paragraph 1...\\n\\nParagraph 2..."}
              ],
              "evidence_log": [
                {"source_index": 1, "paper_title": "Paper Title", "author_year": "Author (Year)", "page_ref": "p. 15", "evidence_summary": "Empirical data or finding utilized in the paragraph"}
              ]
            }
            """
        else:
            format_guideline = f"""
            STRUKTUR FORMAT: Esai Diskusi Mengalir (Tanpa Bab Kaku)
            - Jangan gunakan pembagian bab seperti BAB I, BAB II.
            - Pecah naskah menjadi minimal {min_sections} judul bahasan tematik yang mengalir dinamis.
            - Bahas topik secara komprehensif mulai dari kontekstualisasi masalah, tinjauan teoretis, analisis temuan empiris lintas jurnal, komparasi perspektif para peneliti, implikasi nyata, hingga sintesis penutup.
            - Setiap bagian judul bahasan wajib berisi {paras_per_sec}.
            """
            json_example = """
            {
              "title": "Judul Diskusi Akademis yang Komprehensif",
              "sections": [
                {"heading": "1. Kontekstualisasi dan Akar Permasalahan", "content": "Paragraf 1...\\n\\nParagraf 2..."},
                {"heading": "2. Tinjauan Kerangka Konseptual dan Landasan Teori", "content": "Paragraf 1...\\n\\nParagraf 2..."},
                {"heading": "3. Analisis Kritis Temuan Empiris dan Data Lapangan", "content": "Paragraf 1...\\n\\nParagraf 2..."}
              ],
              "evidence_log": [
                {"source_index": 1, "paper_title": "Judul Paper", "author_year": "Nama (Tahun)", "page_ref": "hlm. X", "evidence_summary": "Poin data atau temuan riset spesifik yang dipakai"}
              ]
            }
            """
    elif format_type == "bernomor":
        if is_en:
            format_guideline = f"""
            FORMAT STRUCTURE: Numbered Assignment Answers (Question 1, 2, etc.)
            - Structure answers into numbered items: '1. [Clear Question/Topic 1]', '2. [Clear Question/Topic 2]', etc.
            - {section_req}
            - Answer each numbered item completely. Analytical items use {paras_per_sec}; factual or short items need only 1 to 2 sentences. Add citations when references are provided.
            """
            json_example = """
            {
              "title": "Assignment 1: Descriptive and Persuasive Writing",
              "sections": [
                {"heading": "1. Analysis of Core Underlying Factors", "content": "Paragraph 1...\\n\\nParagraph 2..."},
                {"heading": "2. Evaluation of Practical Implications", "content": "Paragraph 1...\\n\\nParagraph 2..."}
              ],
              "evidence_log": [
                {"source_index": 1, "paper_title": "Paper Title", "author_year": "Author (Year)", "page_ref": "p. 15", "evidence_summary": "Empirical data or finding utilized in the paragraph"}
              ]
            }
            """
        else:
            format_guideline = f"""
            STRUKTUR FORMAT: Jawaban Tugas Bernomor (Soal 1, 2, dst)
            - Susun jawaban dalam butir-butir nomor terstruktur: '1. [Uraian Pertanyaan atau Topik Pertama]', '2. [Uraian Pertanyaan atau Topik Kedua]', dst.
            - {section_req}
            - Setiap butir nomor dijawab tuntas. Butir analitis memakai {paras_per_sec}, butir faktual atau singkat cukup 1 sampai 2 kalimat. Sertakan sitasi jika ada rujukan.
            """
            json_example = """
            {
              "title": "Tugas 1 Pengantar Ilmu Ekonomi",
              "sections": [
                {"heading": "1. Analisis Faktor Penyebab Utama", "content": "Paragraf 1...\\n\\nParagraf 2..."},
                {"heading": "2. Evaluasi Dampak dan Implementasi", "content": "Paragraf 1...\\n\\nParagraf 2..."}
              ],
              "evidence_log": [
                {"source_index": 1, "paper_title": "Judul Paper", "author_year": "Nama (Tahun)", "page_ref": "hlm. X", "evidence_summary": "Poin data atau temuan riset spesifik yang dipakai"}
              ]
            }
            """
    else:  # makalah
        if is_en:
            format_guideline = f"""
            FORMAT STRUCTURE: Standard Academic Paper (Chapters)
            - Structure with formal chapters: CHAPTER I INTRODUCTION, CHAPTER II DISCUSSION, CHAPTER III CONCLUSION.
            - Produce at least {min_sections} sections/subsections with {paras_per_sec}.
            """
            json_example = """
            {
              "title": "Standard Academic Research Paper",
              "sections": [
                {"heading": "CHAPTER I INTRODUCTION - 1.1 Background", "content": "Paragraph 1...\\n\\nParagraph 2..."},
                {"heading": "CHAPTER II DISCUSSION - 2.1 Theoretical Framework", "content": "Paragraph 1...\\n\\nParagraph 2..."},
                {"heading": "CHAPTER III CONCLUSION - 3.1 Synthesis", "content": "Paragraph 1...\\n\\nParagraph 2..."}
              ],
              "evidence_log": [
                {"source_index": 1, "paper_title": "Paper Title", "author_year": "Author (Year)", "page_ref": "p. 15", "evidence_summary": "Empirical data point"}
              ]
            }
            """
        else:
            if target_words >= 1500:
                format_guideline = f"""
                STRUKTUR FORMAT: Makalah Ilmiah Standar Berskala Penuh
                Naskah WAJIB dipecah menjadi minimal {min_sections} sub-bab terstruktur:
                - BAB I PENDAHULUAN:
                  - 1.1 Latar Belakang Masalah (2 sampai 3 paragraf mendalam dengan fakta konteks)
                  - 1.2 Rumusan Masalah dan Tujuan Penulisan (2 paragraf terstruktur)
                - BAB II PEMBAHASAN:
                  Wajib dipecah menjadi beberapa sub-bab analitis bertema spesifik (misal: 2.1 Landasan Teoretis dan Kerangka Konseptual, 2.2 Analisis Dinamika dan Fakta Lapangan, 2.3 Komparasi Temuan Riset Antar Jurnal, 2.4 Implikasi Psikologis dan Perilaku Nyata, 2.5 Tantangan Kontekstual dan Solusi Alternatif). Setiap sub-bab wajib berisi {paras_per_sec}.
                - BAB III PENUTUP:
                  - 3.1 Kesimpulan Inti (2 paragraf sintesis mendalam)
                  - 3.2 Rekomendasi Solutif dan Arah Pengembangan (2 paragraf aplikatif)
                """
            else:
                format_guideline = f"""
                STRUKTUR FORMAT: Makalah Ilmiah Standar
                - Gunakan struktur bab resmi: BAB I PENDAHULUAN, BAB II PEMBAHASAN, BAB III PENUTUP.
                - Hasilkan minimal {min_sections} bagian/sub-bab dengan {paras_per_sec}.
                """
            json_example = """
            {
              "title": "Judul Makalah Ilmiah Komprehensif",
              "sections": [
                {"heading": "BAB I PENDAHULUAN - 1.1 Latar Belakang Masalah", "content": "Paragraf 1...\\n\\nParagraf 2..."},
                {"heading": "BAB I PENDAHULUAN - 1.2 Rumusan Masalah dan Tujuan", "content": "Paragraf 1...\\n\\nParagraf 2..."},
                {"heading": "BAB II PEMBAHASAN - 2.1 Landasan Teoretis", "content": "Paragraf 1...\\n\\nParagraf 2..."},
                {"heading": "BAB II PEMBAHASAN - 2.2 Analisis Data Empiris Lapangan", "content": "Paragraf 1...\\n\\nParagraf 2..."},
                {"heading": "BAB III PENUTUP - 3.1 Kesimpulan", "content": "Paragraf 1...\\n\\nParagraf 2..."}
              ],
              "evidence_log": [
                {"source_index": 1, "paper_title": "Judul Paper", "author_year": "Nama (Tahun)", "page_ref": "hlm. X", "evidence_summary": "Poin data atau temuan riset spesifik yang dipakai"}
              ]
            }
            """

    # Siapkan bahan bacaan berlabel untuk Gemini dengan isi teks lebih kaya
    sources_text = format_sources_text(papers_with_content)

    if is_en:
        lang_instruction = """
        CRITICAL MANDATORY LANGUAGE ENFORCEMENT:
        - The user assignment topic and instructions are in ENGLISH.
        - You MUST produce 100% of the entire output in natural, fluent ENGLISH.
        - The title, all paragraph texts, headings (if any), and evidence summaries MUST be strictly in English.
        - Under NO circumstances should any Indonesian words appear in the output.
        """
        distortion_rules = """
        STRICT RULES FOR ASSIGNMENT SHEETS AND GUIDELINES (ZERO DISTORTION):
        - Assignment sheets often contain a mix of:
          1. Technical instructions, grading rubrics, guidelines (e.g., 'Word limit 300 words', 'Format: 12pt', 'Avoid plagiarism').
          2. The actual core question or essay prompt to be addressed.
          3. Greeting or administrative announcements.
        - STRICT TREATMENT:
          * (1) Rubrics and technical guidelines serve ONLY as formatting and quality constraints. NEVER answer or treat rubrics as questions or headings.
          * (3) Greetings and administrative announcements MUST BE COMPLETELY EXCLUDED.
          * The ONLY thing to be analyzed, discussed, or answered is (2) the core question or essay topic.
        """
    else:
        lang_instruction = """
        KEPATUHAN BAHASA WAJIB:
        - Topik dan tugas berbahasa INDONESIA.
        - Seluruh keluaran (judul, isi teks naskah, heading jika ada, dan evidence summary) WAJIB ditulis dalam BAHASA INDONESIA yang fasih dan alami.
        """
        distortion_rules = """
        ATURAN MENGENAI LEMBAR SOAL, PETUNJUK TEKNIS, DAN KRITERIA DOSEN (BEBAS DISTORSI):
        - Lembar tugas seringkali memuat campuran antara tiga hal:
          1. Petunjuk teknis, rubrik penilaian, kriteria dosen, atau aturan format (contoh: 'Petunjuk pengerjaan', 'Gunakan modul 3 KB 1', 'Rubrik penilaian: analisis 40%, kesimpulan 20%', 'Format penulisan Times New Roman 12 spasi 1.5', 'Dilarang plagiasi', 'Maksimal 3 halaman').
          2. Pertanyaan inti, butir tugas, atau studi kasus nyata yang harus dipecahkan.
          3. Salam pembuka, sapaan kelas, atau pengantar diskusi (contoh: 'Selamat pagi rekan mahasiswa Tuton UT', 'Selamat datang di sesi 3').
        - PERLAKUAN SANGAT KETAT AGAR JAWABAN TIDAK TENDISTORSI:
          * Bagian (1) kriteria penilaian, rubrik, dan petunjuk teknis HANYA dijadikan pedoman atau rambu-rambu bagaimana kamu menyusun argumen dan teknik sitasi. DILARANG KERAS menjawab kriteria atau petunjuk teknis sebagai nomor soal (contoh: dilarang keras membuat heading seperti '1. Petunjuk Pengerjaan' atau '2. Rubrik Penilaian').
          * Bagian (3) salam pembuka dan obrolan administratif DILARANG dimasukkan ke dalam tulisan jawaban.
          * SATU-SATUNYA yang dijawab, dibedah, dan diuraikan menjadi sub-bab atau butir nomor jawaban adalah bagian (2) pertanyaan inti dan studi kasus yang diujikan dalam tugas tersebut.
          * Jika format bernomor dipilih, nomor 1, 2, dst hanya diberikan untuk menjawab pertanyaan atau kasus inti, BUKAN untuk nomor petunjuk teknis.
        """

    if is_direct_answer:
        length_rules = f"""
    ATURAN JAWABAN LANGSUNG (MENGALAHKAN ATURAN FORMAT DAN PANJANG DI ATAS):
    - Jenis tugas: {DIRECT_ANSWER_LABELS[answer_type]}. Tulis langsung jawabannya. Abaikan target jumlah kata total dan aturan jumlah paragraf; panjang tiap butir mengikuti ATURAN MENJAWAB SETIAP BUTIR di bawah.
    - {section_req if question_count else "Jika soal terdiri dari beberapa bagian dengan instruksi berbeda, buat satu section per bagian dengan heading singkat sesuai instruksinya, lalu jawab setiap butir di baris baru dengan nomor aslinya. Jika hanya satu bagian, tulis dalam satu section tanpa heading."}
    - Untuk terjemahan, terjemahkan lengkap setiap butir dan pertahankan bentuk asli teksnya, misalnya nama pembicara di setiap baris dialog. Tulis setiap giliran bicara di baris baru dengan karakter \\n di dalam 'content'.
    - DILARANG menambah esai pembuka, komentar tentang proses pengerjaan, atau penutup kecuali diminta soal.
    """
    else:
        length_rules = f"""
    ATURAN PANJANG NASKAH DAN KEDALAMAN:
    - Target total panjang naskah: sekitar {target_words} kata (setara kurang lebih {estimated_pages} halaman A4 standar Times New Roman 12pt spasi 1.5). Target ini berlaku untuk bagian yang menuntut uraian, analisis, atau argumentasi.
    - Aturan kedalaman: {depth_instruction}
    - {section_req}
    - Uraikan butir analitis dengan ketebalan argumentasi yang cukup agar naskah mendekati target, tetapi JANGAN menebalkan butir faktual demi mengejar jumlah kata.
    """
    if word_limit:
        length_rules += (
            f"    - Batas kata dari dosen: maksimal {word_limit} kata untuk seluruh jawaban. DILARANG melebihi batas ini. "
            f"Usahakan total antara {bounds['low'] or round(word_limit * 0.9)} dan {bounds['high']} kata, jangan jauh di bawahnya.\n"
        )
    if word_min:
        length_rules += (
            f"    - Batas minimal dari dosen: seluruh jawaban WAJIB paling sedikit {word_min} kata, tidak termasuk judul. Tulis antara {bounds['low']} dan {bounds['high']} kata, target sekitar {bounds['goal']} kata. "
            "Aturan ini MENGALAHKAN anjuran menjawab singkat dan larangan memperpanjang: butir faktual tetap diberi penjelasan, contoh, dan alasan yang relevan "
            "sampai total terpenuhi. DILARANG mengulang kalimat, berputar-putar, atau mengarang fakta untuk menambah panjang.\n"
        )
    item_limits = spec.get("item_word_limits") or []
    if len(item_limits) == 1 and item_limits[0]:
        length_rules += f"    - Batas kata per butir dari dosen: setiap butir maksimal {item_limits[0]} kata. DILARANG melebihi batas ini di butir mana pun.\n"
    elif any(item_limits):
        per_item = ", ".join(f"butir {i} maksimal {n} kata" for i, n in enumerate(item_limits, 1) if n)
        length_rules += f"    - Batas kata per butir dari dosen: {per_item}. DILARANG melebihi batas butir masing-masing, dan jangan memindahkan sisa kata ke butir lain.\n"

    # Pilihan kedalaman pengguna juga berlaku untuk butir pendek, bukan hanya butir uraian
    if paragraph_depth == "elaboratif":
        factual_length = (
            "dijawab 2 sampai 3 kalimat: jawaban inti, lalu kutipan atau parafrase kalimat pendukung dari teks soal "
            "jika teks disediakan, atau penjelasan singkat alasannya jika tidak ada teks"
        )
    else:
        factual_length = "cukup dijawab 1 sampai 2 kalimat"

    # Aturan umum untuk semua jenis soal, supaya perilaku ikut isi soal dan bukan daftar format tertentu
    length_rules += f"""
    ATURAN MENJAWAB SETIAP BUTIR (BERLAKU UNTUK SEMUA FORMAT):
    - Panjang jawaban tiap butir mengikuti apa yang ditanyakan butir itu. Pertanyaan faktual (siapa, kapan, di mana, berapa, sebutkan), isian, pilihan, dan benar salah {factual_length}. Pertanyaan yang meminta penjelasan, analisis, perbandingan, evaluasi, atau argumen diuraikan sesuai aturan kedalaman.
    - Jika butir meminta sejumlah hal (misal 'sebutkan dua', 'mention three', 'what are two'), jawaban WAJIB memuat tepat sejumlah itu dan menyebutnya satu per satu dengan jelas. Ambil hal yang di teks disebut langsung sebagai jawaban pertanyaan itu dan berasal dari kategori yang sama persis dengan yang ditanyakan. Jangan mengisi kekurangan dengan istilah dari kategori lain yang kebetulan mirip, misalnya nama bagian, benda, atau tempat lain yang disebut di dekatnya. Jika teks hanya menyebut lebih sedikit dari yang diminta, pakai bentuk lain yang disebut teks untuk hal yang sama, seperti nama singkatnya.
    - DILARANG menambah latar belakang, pengulangan, atau informasi yang tidak ditanyakan hanya untuk memperpanjang jawaban.
    - Jika lembar soal menyertakan teks bacaan, kasus, data, atau dialog, jawaban wajib bersumber dari teks itu dan tidak boleh bertentangan dengannya. Pengetahuan umum hanya boleh dipakai bila soal memintanya.
    - Untuk pernyataan benar salah, cocokkan setiap kata kunci pernyataan (tujuan, alasan, lokasi, jumlah, waktu, pelaku) dengan teks. Pernyataan yang sebagian isinya bertentangan dengan teks dinilai salah, lalu beri alasan singkat dari teks.
    - Pertahankan nomor butir sesuai lembar soal.
    - Satu butir sering memuat beberapa pertanyaan sekaligus, misal alur perubahan tokoh, bukti kutipan teks, lalu tokoh pilihanmu beserta alasannya. Pecah dulu butir itu menjadi daftar sub-pertanyaan dalam pikiranmu, lalu jawab SETIAP sub-pertanyaan secara tuntas dan proporsional di bagian butir itu. Pertanyaan di ujung kalimat soal sama wajibnya dengan pertanyaan di awal.
    - Jika butir meminta kutipan, bukti teks, atau bunyi pasal, salin kalimat dari teks persis kata per kata di dalam tanda petik ganda "...", lalu jelaskan dengan kalimatmu sendiri kaitan kutipan itu dengan pertanyaan. DILARANG mengganti kutipan dengan parafrase.
    - Soal matematika, logika, statistika, atau hitungan wajib menampilkan langkah pengerjaan baris per baris dengan karakter \\n, mulai dari yang diketahui, rumus atau metode yang dipakai, substitusi, sampai hasil akhir beserta satuannya. Aturan ini MENGALAHKAN aturan gaya paragraf dan batas 1 sampai 2 kalimat.
    - Matriks, tabel kebenaran, peta Karnaugh, dan tabel hasil wajib ditulis lengkap, satu baris per baris dengan pemisah ' | ' dan baris judul kolom. DILARANG hanya menceritakan isinya dalam paragraf.
    - Sebelum menulis hasil akhir, cek silang dengan cara lain, misalnya substitusi balik, minterm dan maxterm yang saling melengkapi sampai 2^n, atau jumlah derajat sama dengan dua kali jumlah sisi.
    - Jika deskripsi gambar mencantumkan 'sisi tidak pasti', kerjakan dengan daftar sisi yang pasti lalu tulis satu kalimat asumsi tentang sisi yang tidak pasti itu.
    - Tulis rumus dengan notasi teks yang terbaca langsung di Word, misalnya x², (x+1)/2, √16, ∑, ≤, dan ×. DILARANG memakai LaTeX seperti \\frac, \\sqrt, atau tanda $.
    - Blok '[Gambar: ...]' di soal adalah deskripsi gambar yang dilampirkan dosen. Jawaban yang merujuk gambar wajib sesuai deskripsi itu. DILARANG mengarang objek, suasana, atau detail yang tidak disebut di deskripsi.
    - Jika angka, label, atau keterangan di gambar berbeda dengan teks soal, kerjakan hitungan utama dengan data teks soal, lalu tutup dengan satu kalimat catatan terpisah yang menyebut perbedaannya dan hasil jika memakai data gambar. Jangan mencampur kedua data di baris yang sama.
    - Baca setiap angka dan simbol di soal persis seperti tertulis. DILARANG menafsirkan ulang angka sebagai salah ketik, misalnya membaca 142 sebagai 14², kecuali gambar dan teks jelas bertentangan.
    - Abaikan petunjuk waktu pengerjaan seperti 'Waktu: 30 menit'. Batas waktu tidak menentukan panjang, kedalaman, atau isi jawaban.
    """
    length_rules += TEXT_FIDELITY_RULES
    if ERROR_TASK.search(topic):
        length_rules += ERROR_TASK_RULES

    if is_math:
        length_rules += """
    PROTOKOL SOAL HITUNGAN EKSAKTA (MENGALAHKAN ATURAN GAYA PARAGRAF, PANJANG, DAN KEDALAMAN):
    - Soal ini soal eksakta (matematika, statistika, fisika, atau algoritma). DILARANG menjawab dengan esai naratif. Tulis setiap langkah di baris sendiri dengan karakter \\n.
    - Setiap butir hitungan WAJIB memakai empat bagian berurutan dengan label persis:
      Diketahui: semua variabel, konstanta, data, dan satuannya, satu per baris. Lalu Ditanya: besaran yang dicari.
      Rumus: rumus, teorema, atau metode yang dipakai, misal Hukum Ampere ∮ B · dl = μ₀ I, eliminasi Gauss-Jordan, atau Master Theorem T(n) = aT(n/b) + f(n).
      Penyelesaian: substitusi angka ke rumus lalu penyederhanaan baris demi baris. DILARANG melompat langsung ke hasil.
      Jawaban: nilai akhir yang tegas beserta satuan SI atau notasi kompleksitas seperti O(n log n).
    - Untuk sistem persamaan, nilai eigen, optimasi, atau persamaan aljabar, substitusikan balik hasilnya ke persamaan awal sampai ruas kiri sama dengan ruas kanan sebelum menulis Jawaban. Tulis satu baris cek singkat.
    - Matriks, tabel kebenaran, tabel distribusi frekuensi, dan peta Karnaugh ditulis satu baris per baris dengan pemisah ' | ' dan baris judul kolom.
    - Pakai simbol Unicode seperti ², ³, ⁻¹, √, ∑, ∫, ≤, ≥, ×, ÷, π, μ, ε, λ, Ω. DILARANG KERAS LaTeX seperti \\frac, \\sqrt, \\begin{matrix}, atau tanda $.
    """

    # Pengguna memilih apakah kutipan langsung diikuti sitasi kurung. Halaman tetap dicatat di evidence_log untuk dicek.
    if quote_citations:
        quote_rule = (
            "Setiap kutipan langsung dalam tanda petik WAJIB diikuti sitasi dengan halaman naskah asli sesuai label halaman di bahan bacaan, "
            "misal (NamaBelakang, Tahun, hlm. 12). Jika label bahan berbentuk 'Bagian n', tulis (NamaBelakang, Tahun) tanpa nomor halaman. DILARANG mengarang nomor halaman."
        )
    else:
        quote_rule = (
            "Kutipan langsung cukup ditulis di dalam tanda petik ganda TANPA sitasi dalam kurung setelahnya, misal (NamaBelakang, Tahun, hlm. 12) DILARANG ditempel setelah kutipan. "
            "Jika memakai lebih dari satu sumber, sebut nama penulis di kalimat pengantar kutipan supaya jelas asalnya, misal 'NamaBelakang menuliskan, \"...\"'. "
            "Tetap catat halaman setiap kutipan di 'evidence_log' sesuai label halaman, dan DILARANG mengarang nomor halaman."
        )

    if papers_with_content and citation_style == "list_only":
        citation_rules = f"""
    ATURAN RUJUKAN DAFTAR PUSTAKA SAJA:
    - Pengguna memilih {len(papers_with_content)} sumber berikut:
{summary_sources_text}
    - Dosen hanya meminta daftar pustaka di akhir. Daftar pustaka disusun otomatis oleh aplikasi, jadi JANGAN menulisnya di 'sections'.
    - Pakai gagasan dari sumber sebagai dasar jawaban, ditulis dengan kalimatmu sendiri.
    - DILARANG sitasi dalam kurung seperti (NamaBelakang, Tahun) atau (NamaBelakang, Tahun, hlm. 12), DILARANG frasa 'Menurut NamaBelakang', dan DILARANG menyebut nama penulis, judul, nama jurnal, atau nomor halaman di badan naskah.
    - Kutipan langsung, jika soal memintanya, cukup di dalam tanda petik ganda tanpa keterangan sumber.
    - Tetap catat sumber yang dipakai di array 'evidence_log' supaya bisa dicek.
    """
    elif papers_with_content:
        # Sitasi dibuat seperti tulisan mahasiswa biasa. Aturan lama yang serba wajib membuat tiap kalimat menyebut sumber dan terbaca lebay.
        citation_rules = f"""
    ATURAN SITASI YANG WAJAR:
    - Pengguna memilih {len(papers_with_content)} sumber berikut:
{summary_sources_text}
    - Sumber adalah pendukung argumen, bukan pusat kalimat. Tulis gagasan dengan kalimatmu sendiri, lalu taruh sitasi singkat di akhir kalimat yang memakai ide sumber itu.
    - Setiap sumber cukup disitir satu atau dua kali di tempat yang paling relevan. Paling banyak satu sitasi per paragraf, dan banyak paragraf memang tidak perlu sitasi sama sekali, terutama pembuka dan refleksi atau pendapat pribadi.
    - Kesimpulan atau penutup DILARANG berisi sitasi atau menyebut sumber. Tulis dengan suara sendiri dari hasil pembahasan.
    - Format sitasi pendek dalam kurung untuk parafrase: (NamaBelakang, Tahun). Untuk modul BMP UT cukup (NamaBelakang, Tahun) atau (Universitas Terbuka, Tahun).
    - Format kutipan langsung: {quote_rule}
    - DILARANG menyebut judul artikel, nama jurnal, kode atau nama mata kuliah, nomor modul, 'materi ...', 'Sumber 1', atau 'penelitian yang dilakukan oleh ... dalam jurnal berjudul ...' di badan naskah.
    - DILARANG frasa pengantar sumber yang berlebihan seperti 'Sebagaimana ditegaskan dalam ...', 'diperkuat oleh pemikiran ...', 'Hal ini sejalan dengan ...', 'Berdasarkan penelitian ...', atau 'Penelitian menunjukkan ...'. 'Menurut NamaBelakang (Tahun)' boleh dipakai paling banyak sekali di seluruh naskah.
    - Contoh buruk: 'Sebagaimana ditegaskan dalam materi MKWN4101 dan diperkuat oleh pemikiran Prakosa (2022, hlm. 51-52), menjalankan kewajiban agama ...'
      Contoh baik: 'Menjalankan kewajiban agama secara benar berjalan beriringan dengan tanggung jawab menjaga kedamaian sosial (Prakosa, 2022).'
    - Modul BMP UT, jika ada, jadi dasar konsep utama. Jurnal lain melengkapi seperlunya.
    - Setiap sitasi harus berdasar isi sumber yang dilampirkan. Catat buktinya di array 'evidence_log'.
    """
        # Bahan bacaan dosen seperti cerpen atau bab buku dianalisis lewat kutipan langsung, bukan parafrase
        if wants_quotes or any(p.get("is_manual_module") and not p.get("is_ut_bmp") for p in papers_with_content):
            citation_rules += """
    ATURAN KUTIPAN LANGSUNG (MENGALAHKAN SARAN PARAFRASE DI ATAS UNTUK BAGIAN YANG MENUNTUT BUKTI TEKS):
    - Bagian yang meminta bukti, kutipan, analisis tokoh, tema, atau bunyi pasal WAJIB memuat kutipan langsung yang disalin persis kata per kata dari bahan bacaan, di dalam tanda petik ganda "...".
    - Format kutipan langsung mengikuti aturan 'Format kutipan langsung' di atas.
    - Di luar tanda petik, uraikan dengan kalimatmu sendiri bagaimana kutipan itu menjawab pertanyaan.
    - Bagian lain yang tidak menuntut bukti teks tetap memakai parafrase biasa.
    """
    else:
        citation_rules = """
    MODE TANPA RUJUKAN (MENGALAHKAN ATURAN FORMAT DAN PANJANG DI ATAS):
    - Pengguna tidak memilih sumber rujukan. DILARANG menulis sitasi seperti (Nama, Tahun), daftar pustaka, atau mengarang sumber apa pun.
    - Kerjakan soal sesuai jenisnya. Jika soal meminta terjemahan, tulis hasil terjemahan lengkap untuk tiap butir soal dan pertahankan bentuk aslinya, misalnya nama pembicara di setiap baris dialog. Buat satu section per butir soal, dan tulis setiap giliran bicara di baris baru dengan karakter \\n di dalam 'content'. Jangan tambahkan esai pembuka, analisis, komentar tentang proses terjemahan, atau penutup kecuali diminta soal.
    - Jika soal meminta terjemahan, hitungan, atau jawaban singkat, abaikan target jumlah kata. Jangan menambah isi hanya demi mengejar panjang.
    - Kosongkan array 'evidence_log'.
    """

    # Judul dan nama penulis diambil dari data nyata, bukan karangan model
    course_line = f"Mata kuliah tugas ini: {course_name}. " if course_name else ""
    if student_name:
        signer_rule = f"Jika naskah butuh nama penulis, misalnya tanda tangan di akhir surat, pakai nama '{student_name}'."
    else:
        signer_rule = "DILARANG mengarang nama penulis. Jika naskah butuh tanda tangan, tulis salam penutupnya saja tanpa nama."
    identity_rules = f"""
    ATURAN JUDUL DAN NAMA PENULIS:
    - {course_line}Isi 'title' dengan nama tugas sesuai lembar soal, misalnya 'Tugas 1 Bahasa Inggris Niaga', atau topik utama soal jika lembar soal tidak menyebut nama tugas. DILARANG judul generik seperti 'Numbered Assignment Answers', 'Jawaban Tugas Kuliah', atau 'Academic Discussion'.
    - {signer_rule}
    - Identitas mahasiswa (nama, NIM, mata kuliah) sudah dicetak otomatis di bawah judul. DILARANG menulisnya lagi di isi naskah.
    """ + task_type_rule(task_type)

    system_instruction = f"""
    Kamu mahasiswa yang menulis jawaban tugas kuliahnya sendiri. Isinya tepat menjawab soal, sedangkan suara tulisannya mengikuti PROFIL GAYA di akhir instruksi ini dan bebas dari ciri khas tulisan AI.

    {lang_instruction}

    {format_guideline}

    {distortion_rules}

    {identity_rules}

    ATURAN TANDA BACA:
    - Pakai tanda baca yang lazim diketik mahasiswa Indonesia: titik, koma, titik dua, tanda tanya, tanda kurung, dan tanda hubung biasa (-).
    - DILARANG memakai em dash (—), en dash (–), atau elipsis satu karakter (…). Ganti dengan koma, titik, atau pecah menjadi kalimat baru.

{length_rules}

{citation_rules}

    GAYA TULISAN (DITARUH TERAKHIR KARENA MENENTUKAN SUARA SELURUH NASKAH):
    - Aturan format, jumlah butir, langkah hitungan, kutipan, sitasi, dan batas kata di atas tetap wajib. Ada atau tidaknya sitasi ditentukan rujukan yang dipilih mahasiswa, bukan oleh gaya. Gaya di bawah mengatur cara menulisnya, bukan isinya.
    {voice_rules(tone, is_en)}

    BAHASA KELUARAN WAJIB: {'ENGLISH. Seluruh judul dan isi naskah ditulis dalam bahasa Inggris, walau instruksi ini berbahasa Indonesia.' if is_en else 'BAHASA INDONESIA.'}

    FORMAT KELUARAN (JSON MURNI DAN SAH, setiap nilai string ditulis utuh tanpa tanda + penyambung):
    {json_example}
    """

    if not papers_with_content:
        sources_block = "No references selected. Answer directly without citations." if is_en else "Tidak ada rujukan dipilih. Jawab langsung tanpa sitasi."
    elif is_en:
        sources_block = f"SELECTED REFERENCES:\n{summary_sources_text}\n\nSOURCE MATERIALS AND READING EXCERPTS:\n{sources_text}"
    else:
        sources_block = f"SUMBER RUJUKAN TERPILIH:\n{summary_sources_text}\n\nBAHAN BACAAN SUMBER RESMI:\n{sources_text}"

    # Jawaban langsung tidak boleh didorong target kata dan analisis mendalam, karena model akan menggembungkan jawaban singkat
    if is_direct_answer:
        length_line_en = "Target Length: follow the direct answer rules, no word target"
        length_line_id = "Target Panjang: ikuti aturan jawaban langsung, tanpa target jumlah kata"
        default_extra_en = "Answer each item directly and concisely."
        default_extra_id = "Jawab setiap butir secara langsung dan ringkas."
    else:
        length_line_en = f"Target Length: approximately {target_words} words (estimated {estimated_pages} pages)"
        length_line_id = f"Target Panjang: sekitar {target_words} kata (estimasi {estimated_pages} halaman A4)"
        default_extra_en = "Answer everything the prompt asks, completely."
        default_extra_id = "Jawab tuntas setiap hal yang ditanyakan soal."

    if is_en:
        user_prompt = f"""
        Write a complete university assignment answer based on the following prompt and reference materials.

        Assignment Topic / Prompt: {topic}
        Format Structure: {format_type}
        {length_line_en}
        Paragraph Depth: {depth_instruction}
        Tone: {tone}
        Additional Instructions: {custom_instructions or default_extra_en}

        {sources_block}
        """
    else:
        user_prompt = f"""
        Tuliskan jawaban tugas kuliah yang lengkap berdasarkan soal dan bahan rujukan berikut.

        Topik atau Pertanyaan Tugas: {topic}
        Bentuk Format: {format_type}
        {length_line_id}
        Kedalaman Paragraf: {depth_instruction}
        Gaya Nada: {tone}
        Instruksi Tambahan: {custom_instructions or default_extra_id}

        {sources_block}
        """

    # Soal hitungan dan logika sering salah tanpa mode berpikir. Esai dan makalah tidak butuh dan jadi jauh lebih lambat.
    needs_reasoning = is_direct_answer or is_math or (answer_type not in ("esai", "makalah") and bool(REASONING_HINT.search(topic)))
    # Jawaban yang JSON-nya rusak dicoba ulang sekali. Teks mentah dari model tidak pernah ditampilkan sebagai naskah,
    # karena dulu hasilnya berupa kode JSON utuh di kertas dan seluruh soal jadi judul.
    parsed = None
    for _attempt in range(2):
        response = await generate_with_fallback(
            "generation",
            user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.4,
                # 8192 memotong JSON untuk target 3000+ kata
                max_output_tokens=32768,
                response_mime_type="application/json",
                thinking_config=types.ThinkingConfig(thinking_level="high") if needs_reasoning else None,
            ),
            timeout=150.0 if needs_reasoning else 75.0,
            total_budget=300.0 if needs_reasoning else 240.0,
        )
        parsed = robust_json_dict_parse(response.text)
        if isinstance(parsed, dict) and any(isinstance(sec, dict) and str(sec.get("content") or "").strip() for sec in parsed.get("sections") or []):
            break
        print("Peringatan: Gemini mengirim naskah dengan format rusak, dicoba ulang sekali.")
    else:
        raise RuntimeError("Gemini dua kali mengirim naskah dengan format rusak.")

    language = "en" if is_en else "id"

    # Rapikan keluaran model agar exporter tidak crash oleh nilai null atau tipe salah
    sections = [
        {
            # Deskripsi gambar hanya bahan baca model, tidak perlu ikut di judul butir
            "heading": clean_output_text(IMAGE_BLOCK.sub("", str(sec.get("heading") or ""))),
            "content": clean_output_text(str(sec.get("content") or "")),
        }
        for sec in parsed.get("sections") or []
        if isinstance(sec, dict)
    ]
    # Model kadang tetap menempel sitasi yang tidak diminta pengguna
    for sec in sections:
        sec["content"] = finalize_text(sec["content"], quote_citations, citation_style)
    # Postingan forum satu bagian tidak butuh judul bagian, model kadang tetap membuatnya seperti 'IDENTIFYING MISTAKES'
    if task_type == "ut-diskusi" and len(sections) == 1:
        sections[0]["heading"] = ""
    # Heading bagian wajib dikunci persis sesuai tulisan dosen, model sering menambah nomor atau kata BAB
    if format_type == "wajib" and len(sections) == len(required_sections):
        for name, sec in zip(required_sections, sections):
            sec["heading"] = name

    # Jaring pengaman: model kadang tetap mengosongkan heading, padahal tiap butir wajib bernomor sesuai lembar soal
    if format_type == "bernomor" and len(sections) == question_count:
        for number, sec in enumerate(sections, 1):
            if not re.match(rf"\s*{number}\s*[.)]", sec["heading"]):
                sec["heading"] = f"{number}. {sec['heading']}".strip()

    # Model sering tetap melewati batas kata dosen per butir, jadi butir yang kelewatan dipangkas ulang sekali
    limits_per_section = item_limits * len(sections) if len(item_limits) == 1 else item_limits
    if len(sections) == len(limits_per_section):
        for index, limit in enumerate(limits_per_section):
            if not limit or len(sections[index]["content"].split()) <= limit:
                continue
            try:
                sections[index] = await rewrite_section(
                    topic, sections, index, language=language,
                    instruction=f"Persingkat bagian ini jadi sekitar {round(limit * 0.9)} kata tanpa membuang poin yang diminta soal.",
                    word_limit=limit, papers=papers_with_content, guidelines=custom_instructions, student_name=student_name,
                    quote_citations=quote_citations, task_type=task_type, tone=tone, citation_style=citation_style,
                )
            except Exception as e:
                print(f"Peringatan: gagal memangkas butir {index + 1} ke batas {limit} kata: {e}")

    # Model meleset sekitar 20 persen dari target ke dua arah, jadi naskah di luar rentang dosen disesuaikan sekali
    # dalam satu panggilan untuk seluruh naskah, bukan satu panggilan per bagian.
    bounds = length_bounds(word_min, word_limit)
    # Terjemahan dan jawaban singkat mengikuti teks soal, jadi panjangnya tidak boleh diubah demi target kata
    if bounds and sections and not is_direct_answer:
        total = sum(len(sec["content"].split()) for sec in sections)
        if total < bounds["low"] or (bounds["trigger_high"] and total > bounds["trigger_high"]):
            try:
                sections = await adjust_total_length(
                    topic, sections, bounds, language=language, papers=papers_with_content, quote_citations=quote_citations,
                    tone=tone, task_type=task_type, citation_style=citation_style,
                )
            except Exception as e:
                print(f"Peringatan: gagal menyesuaikan panjang naskah {total} kata ke rentang dosen: {e}")
    if is_personal_letter and sections:
        sections[0]["content"] = LETTER_GREETING.sub(r"\1\n\n", sections[0]["content"])
        sections[-1]["content"] = LETTER_SIGNOFF.sub(r"\n\n\1\n\2", sections[-1]["content"])
    return {
        # Tanpa judul dari model, pakai baris pertama soal yang dipendekkan, bukan seluruh soal
        "title": clean_output_text(str(parsed.get("title") or "")) or topic.strip().split("\n")[0][:80],
        "sections": sections,
        "evidence_log": parsed.get("evidence_log") or [],
        "language": language,
    }



def length_bounds(word_min: Optional[int], word_limit: Optional[int]) -> Optional[Dict[str, int]]:
    """
    Rentang panjang dari batas dosen. low dan high dipakai di prompt, goal jadi target, trigger_high batas sebelum dipangkas.
    Hanya minimal: 800 sampai 1.000 kata, target 880, tidak dipangkas. Hanya maksimal: 90 sampai 100 persen batas.
    """
    if word_min and word_limit and word_limit > word_min:
        return {"low": word_min, "high": word_limit, "goal": round((word_min + word_limit) / 2), "trigger_high": word_limit}
    if word_min:
        # Lebih panjang dari minimal tidak melanggar aturan dosen. Uji nyata menunjukkan model cadangan saat kuota padat
        # memangkas kebablasan sampai di bawah minimal atau mengabaikan instruksi, jadi kelebihan tidak dipangkas otomatis.
        return {"low": word_min, "high": round(word_min * 1.25), "goal": round(word_min * 1.1), "trigger_high": None}
    if word_limit:
        # Di bawah batas maksimal tidak melanggar aturan dosen, jadi tidak dipanjangkan otomatis
        return {"low": 0, "high": word_limit, "goal": round(word_limit * 0.95), "trigger_high": word_limit}
    return None


async def adjust_total_length(
    topic: str,
    sections: List[Dict[str, str]],
    bounds: Dict[str, int],
    language: str = "id",
    papers: Optional[List[Dict[str, Any]]] = None,
    quote_citations: bool = False,
    tone: str = "",
    task_type: Optional[str] = None,
    citation_style: str = "in_text",
) -> List[Dict[str, str]]:
    """Memanjangkan atau memendekkan seluruh naskah ke rentang dosen dalam satu panggilan. Naskah asli dikembalikan jika hasilnya tidak valid."""
    total = sum(len(sec["content"].split()) for sec in sections)
    goal = bounds["goal"]
    direction = "Panjangkan" if total < goal else "Persingkat"
    # Target per bagian lebih mudah diikuti model daripada satu angka total, yang sering dipangkas atau ditambah kebablasan
    targets = [max(30, round(len(sec["content"].split()) * goal / total)) for sec in sections]
    draft = "\n\n".join(
        f"[BAGIAN {i + 1}: sekarang {len(sec['content'].split())} kata, ubah menjadi sekitar {target} kata]\n{sec['heading']}\n{sec['content']}"
        for i, (sec, target) in enumerate(zip(sections, targets))
    )
    system_instruction = f"""
    Kamu mahasiswa yang menyesuaikan panjang naskah tugasnya sendiri tanpa mengubah isi jawabannya.
    - Total isi sekarang {total} kata. {direction} menjadi sekitar {goal} kata, paling sedikit {bounds['low']} dan paling banyak {bounds['high']} kata, tidak termasuk heading.
    - Ikuti target kata yang tertulis di label setiap bagian. Selisih tiap bagian paling banyak 10 persen dari targetnya.
    - Jika memanjangkan, tambah penjelasan, contoh, dan alasan yang relevan dengan soal dan materi. Jika memendekkan, buang pengulangan dan kalimat yang paling tidak penting.
    - Pertahankan jumlah dan urutan bagian, heading, semua poin yang diminta soal, kutipan langsung persis kata per kata, dan sitasi.
    - DILARANG mengulang kalimat, berputar-putar, atau mengarang fakta. DILARANG memakai tag HTML, markdown, em dash, atau LaTeX.
    - Bahasa keluaran: {'ENGLISH' if language == 'en' else 'BAHASA INDONESIA'}.
    {revision_style_rules(tone, language == 'en')}{TEXT_FIDELITY_RULES}{task_type_rule(task_type)}
    FORMAT KELUARAN (JSON MURNI): {{"sections": [{{"heading": "...", "content": "..."}}]}}
    """
    user_prompt = f"LEMBAR SOAL:\n{topic}\n\nNASKAH SEKARANG:\n{draft}\n"
    if papers:
        user_prompt += f"\nBAHAN SUMBER:\n{format_sources_text(papers)}\n"

    response = await generate_with_fallback(
        "generation",
        user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.3,
            max_output_tokens=32768,
            response_mime_type="application/json",
        ),
        timeout=120.0,
        total_budget=200.0,
    )
    parsed = robust_json_dict_parse(response.text) or {}
    new_sections = [sec for sec in parsed.get("sections") or [] if isinstance(sec, dict)]
    # Bagian yang hilang atau bertambah berarti model merombak struktur, jadi naskah asli lebih aman
    if len(new_sections) != len(sections):
        raise ValueError(f"jumlah bagian berubah dari {len(sections)} menjadi {len(new_sections)}")
    adjusted = []
    for old, new in zip(sections, new_sections):
        content = clean_output_text(str(new.get("content") or ""))
        if not content.strip():
            raise ValueError("ada bagian kosong")
        adjusted.append({"heading": old["heading"], "content": finalize_text(content, quote_citations, citation_style)})
    # Model yang memangkas atau menambah kebablasan bisa membuat naskah makin jauh dari aturan dosen, jadi hasilnya dicek dulu
    new_total = sum(len(sec["content"].split()) for sec in adjusted)
    if new_total < bounds["low"] and new_total < total:
        raise ValueError(f"hasil penyesuaian {new_total} kata malah di bawah batas minimal {bounds['low']}")
    if abs(new_total - goal) >= abs(total - goal):
        raise ValueError(f"hasil penyesuaian {new_total} kata tidak lebih dekat ke target {goal} daripada {total}")
    return adjusted


# Arahan cepat dari tombol pilihan di Tahap 3. Teksnya tetap di server supaya perintah ke model selalu sama.
REWRITE_PRESETS = {
    "clarify": "Perjelas kalimat yang berbelit dan rapikan alurnya. Isi, poin, dan contoh tetap sama.",
    "example": "Tambahkan satu contoh konkret yang relevan dengan soal, misalnya pelaku, situasi, atau angka tertentu. DILARANG mengarang data penelitian atau sumber.",
    "natural": "Buat terasa lebih natural seperti tulisan mahasiswa: kalimat lebih pendek, kata sehari-hari, tanpa ungkapan klise dan kata sok pintar.",
    "formal": "Buat lebih formal dengan bahasa baku dan kalimat efektif, tanpa kata santai.",
}
REWRITE_LENGTHS = {
    "shorter": "Persingkat jadi sekitar 70 persen panjang sekarang tanpa membuang poin yang diminta soal.",
    "longer": "Perpanjang jadi sekitar 130 persen panjang sekarang dengan penjelasan atau contoh yang relevan, bukan pengulangan.",
}


def build_revision_instruction(instruction: str = "", presets=(), length: str = "same") -> str:
    """Menggabungkan arahan cepat, pilihan panjang, dan arahan bebas jadi satu arahan revisi."""
    lines = [REWRITE_PRESETS[p] for p in presets if p in REWRITE_PRESETS]
    if length in REWRITE_LENGTHS:
        lines.append(REWRITE_LENGTHS[length])
    if instruction.strip():
        lines.append(instruction.strip())
    return " ".join(lines)


def split_paragraphs(content: str):
    """Memecah isi bagian per baris seperti tampilan Tahap 3. Pemisah ikut disimpan supaya paragraf lain bisa disambung ulang persis."""
    parts = re.split(r"(\n+)", content or "")
    return parts, [i for i in range(0, len(parts), 2) if parts[i].strip()]


async def rewrite_section(
    topic: str,
    sections: List[Dict[str, str]],
    index: int,
    language: str = "id",
    instruction: str = "",
    word_limit: Optional[int] = None,
    papers: Optional[List[Dict[str, Any]]] = None,
    guidelines: str = "",
    student_name: str = "",
    quote_citations: bool = True,
    task_type: Optional[str] = None,
    tone: str = "",
    citation_style: str = "in_text",
    paragraph: Optional[int] = None,
    presets=(),
    length: str = "same",
) -> Dict[str, str]:
    """
    Menulis ulang satu bagian jawaban tanpa menyentuh bagian lain, mengikuti arahan pengguna jika ada.
    paragraph terisi berarti hanya satu paragraf yang ditulis ulang. Paragraf lain disambung ulang di sini, bukan oleh model.
    """
    if not 0 <= index < len(sections):
        raise ValueError("Nomor bagian di luar jangkauan.")

    is_en = language == "en"
    target = sections[index]
    instruction = build_revision_instruction(instruction, presets, length)
    parts, paragraph_slots = split_paragraphs(target.get("content", ""))
    if paragraph is not None and not 0 <= paragraph < len(paragraph_slots):
        raise ValueError("Nomor paragraf di luar jangkauan.")
    old_paragraph = parts[paragraph_slots[paragraph]] if paragraph is not None else ""
    draft = "\n\n".join(
        f"[BAGIAN {i + 1}{' (YANG DITULIS ULANG)' if i == index else ''}]\n{s.get('heading', '')}\n{s.get('content', '')}"
        for i, s in enumerate(sections)
    )
    if papers and citation_style == "list_only":
        citation_rule = (
            "Rujukan tugas ini hanya dicantumkan di daftar pustaka. DILARANG sitasi kurung, frasa 'Menurut NamaBelakang', "
            "menyebut nama penulis, atau nomor halaman di isi bagian. Kutipan langsung cukup bertanda petik dan disalin persis dari BAHAN SUMBER."
        )
    elif papers:
        ref_lines = "\n".join(
            f"- {', '.join(p.get('authors') or ['Anonim'])} ({p.get('year') or 'n.d.'}). {p.get('title', '')}"
            for p in papers
        )
        citation_rule = (
            f"Pertahankan sitasi parafrase yang ada. Sitasi hanya boleh merujuk daftar ini:\n{ref_lines}\n"
            "    - Kutipan langsung dalam tanda petik wajib disalin persis dari BAHAN SUMBER. DILARANG mengubah isi kutipan atau mengarang halaman.\n"
            + ("    - Setiap kutipan langsung diikuti sitasi dengan nomor halaman sesuai label halamannya."
               if quote_citations else
               "    - Kutipan langsung cukup bertanda petik TANPA sitasi dalam kurung setelahnya. Buang sitasi kurung yang menempel setelah kutipan.")
        )
    else:
        citation_rule = "Tugas ini tanpa rujukan. DILARANG menulis sitasi atau mengarang sumber."
    if paragraph is None:
        scope_rule = "Kamu mahasiswa yang merevisi SATU bagian jawaban tugasnya sendiri. Revisi hanya bagian yang ditandai, dengan suara mahasiswa yang alami dan bebas klise AI."
        output_rule = "Jangan mengulang isi bagian lain. Tulis isi bagiannya saja tanpa heading."
        limit_rule = f"Bagian ini maksimal {word_limit} kata." if word_limit else "Panjang kurang lebih sama dengan versi sekarang kecuali arahan meminta lain."
    else:
        scope_rule = (
            f"Kamu mahasiswa yang merevisi SATU paragraf, yaitu paragraf ke-{paragraph + 1} di bagian {index + 1}. "
            "Paragraf lain tetap persis seperti sekarang dan tidak ikut ditulis. Revisi dengan suara mahasiswa yang alami dan bebas klise AI."
        )
        output_rule = "Tulis isi paragraf baru saja sebagai satu paragraf tanpa baris baru. Paragraf baru harus tetap nyambung dengan paragraf sebelum dan sesudahnya."
        other_words = len(" ".join(parts[i] for i in paragraph_slots if i != paragraph_slots[paragraph]).split())
        limit_rule = (
            f"Seluruh bagian maksimal {word_limit} kata, jadi paragraf baru paling banyak {max(20, word_limit - other_words)} kata."
            if word_limit else "Panjang paragraf kurang lebih sama dengan versi sekarang kecuali arahan meminta lain."
        )
    signer_rule = (
        f"Jika bagian ini butuh nama penulis, pakai nama '{student_name}'."
        if student_name else "DILARANG mengarang nama penulis."
    )

    system_instruction = f"""
    {scope_rule}
    - Ini REVISI, bukan menulis dari nol. Pertahankan poin, urutan argumen, contoh, kutipan langsung, sitasi, jumlah paragraf, dan panjang versi sekarang. Ubah hanya yang diminta arahan revisi. Tanpa arahan, cukup perbaiki kejelasan kalimat, alur, dan salah ketik.
    - Ganti, tambah, atau buang poin dan kutipan HANYA jika arahan revisi memintanya.
    - Tulis teks biasa. DILARANG memakai tag HTML seperti <p> atau <br>, dan DILARANG markdown seperti ** atau #.
    - Bahasa keluaran: {'ENGLISH' if is_en else 'BAHASA INDONESIA'}.
    - Jawaban tetap harus menjawab butir soal yang sama sesuai lembar soal dan petunjuk dosen. Jika soal merujuk blok '[Gambar: ...]', jangan mengarang detail di luar deskripsi itu.
    - {limit_rule}
    - {citation_rule}
    - {signer_rule}
    - {output_rule}
    - DILARANG memakai em dash, en dash, atau LaTeX. Pisahkan paragraf dengan \n\n.
    {revision_style_rules(tone, is_en)}{TEXT_FIDELITY_RULES}{task_type_rule(task_type)}
    FORMAT KELUARAN (JSON MURNI): {{"content": "..."}}
    """
    user_prompt = f"""
    LEMBAR SOAL:
    {topic}

    PETUNJUK DOSEN:
    {guidelines or '-'}

    NASKAH SEKARANG:
    {draft}

    ARAHAN REVISI DARI MAHASISWA: {instruction.strip() or 'Tidak ada arahan khusus. Perbaiki kejelasan kalimat dan alur seperlunya, isi dan kutipan tetap sama.'}
    """
    if paragraph is not None:
        user_prompt += f"\n    PARAGRAF YANG DITULIS ULANG (paragraf ke-{paragraph + 1} di bagian {index + 1}):\n    {old_paragraph.strip()}\n"
    # Tanpa isi naskah, model tidak bisa mengecek kutipan, halaman, dan siapa yang berbicara saat menulis ulang
    if papers:
        user_prompt += f"\n    BAHAN SUMBER:\n{format_sources_text(papers)}\n"

    response = await generate_with_fallback(
        "generation",
        user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            # Suhu rendah supaya revisi tidak melenceng jauh dari versi awal
            temperature=0.3,
            max_output_tokens=8192,
            response_mime_type="application/json",
            thinking_config=types.ThinkingConfig(thinking_level="high") if REASONING_HINT.search(topic) else None,
        ),
        timeout=90.0,
        total_budget=180.0,
    )
    # Pengurai yang sama dengan naskah utuh, supaya JSON dengan blok markdown atau string tersambung tetap terbaca
    parsed = robust_json_dict_parse(response.text)
    if not isinstance(parsed, dict) or not str(parsed.get("content") or "").strip():
        raise RuntimeError("Gemini tidak mengembalikan bagian yang bisa dipakai.")
    # Heading dipertahankan apa adanya supaya nomor butir tidak hilang. Pengguna bisa mengubahnya lewat Edit.
    content = finalize_text(clean_output_text(str(parsed["content"])), quote_citations, citation_style)
    if paragraph is not None:
        # Model kadang memecah jawaban jadi beberapa baris. Satu paragraf diganti satu paragraf, sisanya disambung persis.
        parts[paragraph_slots[paragraph]] = re.sub(r"\s*\n+\s*", " ", content).strip()
        content = "".join(parts)
    return {"heading": target.get("heading", ""), "content": content}
