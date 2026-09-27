import json
import asyncio
from typing import List, Dict, Any
from google.genai import types
from tools.gemini_client import get_gemini_client


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


async def generate_academic_draft(
    topic: str,
    papers_with_content: List[Dict[str, Any]],
    format_type: str = "otomatis",
    target_words: int = 1000,
    paragraph_depth: str = "standar",
    tone: str = "akademis formal",
    custom_instructions: str = ""
) -> Dict[str, Any]:
    """Menyusun naskah tugas berbasis fakta dan nomor halaman dari dokumen yang diunduh."""
    client = get_gemini_client()

    is_en = detect_language(topic, custom_instructions) == "en"
    estimated_pages = max(1, round(target_words / 280))

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
    if format_type == "esai":
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
            - Provide at least {min_sections} detailed points or sub-questions.
            - Each numbered item must be thoroughly answered with {paras_per_sec} and citations.
            """
            json_example = """
            {
              "title": "Numbered Assignment Answers",
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
            - Hasilkan minimal {min_sections} butir nomor atau sub-pertanyaan terperinci.
            - Setiap butir nomor wajib dijawab secara tuntas dengan {paras_per_sec} disertai sitasi naskah asli.
            """
            json_example = """
            {
              "title": "Jawaban Tugas Kuliah",
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
    sources_text = ""
    for idx, p in enumerate(papers_with_content, 1):
        authors = ", ".join(p.get("authors", ["Anonim"]))
        year = p.get("year") or "n.d."
        title = p.get("title", "")
        pages_content = p.get("pages_content", [])
        if p.get("is_manual_module"):
            status_label = "Buku Materi Pokok (BMP) UT / Diktat Bahan Ajar"
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
            text_snippet = page.get("text", "")[:1500]
            sources_text += f"[{page_num}]: {text_snippet}\n"

    if is_en:
        lang_instruction = """
        CRITICAL MANDATORY LANGUAGE ENFORCEMENT:
        - The user assignment topic and instructions are in ENGLISH.
        - You MUST produce 100% of the entire output in natural, fluent, and rigorous academic ENGLISH.
        - The title, all paragraph texts, headings (if any), and evidence summaries MUST be strictly in English.
        - Under NO circumstances should any Indonesian words appear in the output.
        """
        student_voice_rules = """
        RULES FOR GENUINE STUDENT VOICE AND TONE:
        1. Adopt the voice of an articulate, genuine university student who truly understands the subject matter.
        2. STRICTLY FORBIDDEN to include any opening salutations (e.g. 'Hello Tutor', 'Dear Lecturer', 'Good morning').
        3. STRICTLY FORBIDDEN to include robotic boilerplate conclusions (e.g. 'In conclusion', 'That concludes my answer', 'Hope this helps').
        4. Begin immediately with the opening paragraph or first heading.
        5. FORBIDDEN AI CLICHES: Do NOT use overused AI tells such as 'delve', 'crucial', 'multifaceted', 'pivotal', 'testament', 'tapestry', 'it is important to note', 'underscores', 'in today's modern era', 'beacon', 'foster', 'moreover' at the start of every sentence.
        6. When the assignment asks for personal preference or opinion (e.g., 'explain your personal preference'), write naturally using first-person perspective ('I prefer...', 'In my view...') backed by solid reasoning and scholarly evidence.
        7. Provide clear reasoning with grounded, concrete examples.
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
        - Seluruh keluaran (judul, isi teks naskah, heading jika ada, dan evidence summary) WAJIB ditulis dalam BAHASA INDONESIA yang ilmiah, fasih, dan alami.
        """
        student_voice_rules = """
        ATURAN GAYA DAN NADA BICARA MAHASISWA ASLI:
        1. Gunakan suara mahasiswa tulen yang benar-benar memahami materi, bukan ensiklopedia kaku atau robot bot.
        2. DILARANG KERAS menyertakan sapaan pembuka apapun (seperti 'Halo Tutor', 'Selamat pagi', 'Terima kasih atas pertanyaannya').
        3. DILARANG KERAS menyertakan kata penutup klise apapun (seperti 'Demikian jawaban saya', 'In conclusion', 'Semoga membantu').
        4. Langsung mulai dari inti pembahasan atau judul bagian pertama.
        5. HINDARI struktur daftar poin (bullet points) tebal yang berlebihan. Utamakan paragraf-paragraf yang bersih, mengalir logis, dan saling terhubung.
        6. DILARANG menggunakan kata-kata klise sok pintar khas AI: 'krusial', 'esensial', 'ranah', 'delve', 'crucial', 'multifaceted', 'pivotal', 'secara keseluruhan', 'penting untuk dicatat', 'menggarisbawahi', 'menatap masa depan', 'dalam era modern ini'.
        7. Tulis secara alami dari sudut pandang pemikiran mahasiswa (boleh menggunakan 'saya' jika relevan untuk analisis tugas atau pandangan pribadi).
        8. Berikan penalaran yang jelas dengan contoh konkret dan membumi.
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

    system_instruction = f"""
    Kamu adalah mahasiswa berprestasi yang sedang menulis naskah tugas kuliah ilmiah berkualitas tinggi. Tugasmu menyusun tulisan yang berbobot, kritis, membumi, dan sepenuhnya bebas dari ciri khas tulisan AI.

    {lang_instruction}

    {format_guideline}

    {student_voice_rules}

    {distortion_rules}

    ATURAN SITASI KHUSUS MODUL BMP UT ATAU BAHAN AJAR KAMPUS:
    - Jika terdapat sumber berlabel 'Buku Materi Pokok (BMP) UT / Diktat Bahan Ajar', perlakukan sumber ini sebagai fondasi konseptual utama tugas kuliah.
    - Wajib kutip materi modul tersebut sesuai format baku akademik, contoh: (Kuswandi, 2023, Modul 3, hlm. 3.14) atau (Universitas Terbuka, 2023, Modul 2) atau menurut BMP Modul X.
    - Hubungkan teori dari modul UT tersebut dengan data empiris dari naskah jurnal lainnya secara harmonis.

    ATURAN PANJANG NASKAH DAN KEDALAMAN (SANGAT KETAT):
    - Target total panjang naskah: sekitar {target_words} kata (setara kurang lebih {estimated_pages} halaman A4 standar Times New Roman 12pt spasi 1.5).
    - Aturan kedalaman: {depth_instruction}
    - {section_req}
    - Tulislah dengan ketebalan argumentasi yang tepat agar total panjang naskah mendekati target {target_words} kata.

    MANDAT SITASI SELURUH SUMBER TERVERIFIKASI (WAJIB 100%):
    - Pengguna telah memilih {len(papers_with_content)} sumber naskah ilmiah berikut:
{summary_sources_text}
    - Kamu WAJIB menyitir, membahas, dan menghubungkan SELURUH {len(papers_with_content)} sumber di atas di dalam badan naskah! DILARANG KERAS mengabaikan sumber manapun. Setiap naskah minimal harus disitir setidaknya satu kali.
    - Format sitasi di dalam teks: (NamaBelakangPenulis, Tahun, hlm. X) atau (NamaBelakangPenulis, Tahun).
    - Setiap sitasi harus memiliki dasar bukti nyata dari teks sumber yang dilampirkan.
    - Catat setiap bukti kutipan pada array 'evidence_log'.

    FORMAT KELUARAN (JSON MURNI):
    {json_example}
    """

    if is_en:
        user_prompt = f"""
        Write a complete and rigorous university assignment response based on the following assignment topic and verified reference materials.

        Assignment Topic / Prompt: {topic}
        Format Structure: {format_type}
        Target Length: approximately {target_words} words (estimated {estimated_pages} pages)
        Paragraph Depth: {depth_instruction}
        Tone: {tone}
        Additional Instructions: {custom_instructions if custom_instructions else 'Provide deep analysis, grounded reasoning, and coherent paragraph flow.'}

        LIST OF ALL VERIFIED REFERENCES (ALL MUST BE CITED):
        {summary_sources_text}

        SOURCE MATERIALS AND READING EXCERPTS:
        {sources_text}
        """
    else:
        user_prompt = f"""
        Tuliskan naskah tugas kuliah lengkap dan mendalam berdasarkan topik dan bahan rujukan nyata berikut.

        Topik atau Pertanyaan Tugas: {topic}
        Bentuk Format: {format_type}
        Target Panjang: sekitar {target_words} kata (estimasi {estimated_pages} halaman A4)
        Kedalaman Paragraf: {depth_instruction}
        Gaya Nada: {tone}
        Instruksi Tambahan: {custom_instructions if custom_instructions else 'Jawab dengan analisis mendalam, membumi, dan terhubung antar argumen.'}

        DAFTAR SELURUH SUMBER YANG WAJIB DISITASI:
        {summary_sources_text}

        BAHAN BACAAN SUMBER RESMI:
        {sources_text}
        """

    # Rantai cadangan model agar tahan banting saat server Google sedang padat antrean
    candidate_models = [
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
        "gemini-2.5-flash-lite",
        "gemini-3-flash-preview",
        "gemini-flash-latest"
    ]

    last_error = None
    response = None

    for model_name in candidate_models:
        try:
            print(f"Mencoba menyusun dengan model: {model_name} (Target: {target_words} kata)")
            response = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model=model_name,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=0.4,
                        # 8192 memotong JSON untuk target 3000+ kata
                        max_output_tokens=32768,
                        response_mime_type="application/json",
                    )
                ),
                timeout=75.0
            )
            if response and response.text:
                print(f"Sukses mendapatkan respons dari model: {model_name}")
                break
        except Exception as e:
            print(f"Model {model_name} sedang sibuk atau limit ({e}), beralih ke model cadangan berikutnya...")
            last_error = e

    if not response or not response.text:
        raise RuntimeError(f"Seluruh model Gemini sedang mengalami lonjakan antrean: {last_error}")

    language = "en" if is_en else "id"
    try:
        parsed = json.loads(response.text)
    except ValueError as e:
        print(f"Error parsing Gemini JSON response: {e}")
        parsed = None
    if isinstance(parsed, list) and parsed:
        parsed = parsed[0]
    if not isinstance(parsed, dict):
        return {
            "title": topic.title(),
            "sections": [
                {"heading": "" if format_type in ("esai", "otomatis") else ("Main Analysis" if is_en else "Analisis Utama"), "content": response.text}
            ],
            "evidence_log": [],
            "language": language,
        }

    # Rapikan keluaran model agar exporter tidak crash oleh nilai null atau tipe salah
    sections = [
        {"heading": str(sec.get("heading") or ""), "content": str(sec.get("content") or "")}
        for sec in parsed.get("sections") or []
        if isinstance(sec, dict)
    ]
    return {
        "title": str(parsed.get("title") or topic.title()),
        "sections": sections,
        "evidence_log": parsed.get("evidence_log") or [],
        "language": language,
    }

