# Technical Architecture Specification: Multi-Part Question Resolution, Direct Textual Evidence, and Deterministic STEM Computation

Status: Production-Grade Architectural Specification. Dokumen ini dirancang dengan terminologi rekayasa perangkat lunak standar industri dan teknik orkestrasi LLM presisi tinggi untuk memudahkan Claude dalam mengeksekusi modifikasi kode tanpa ambiguitas.

---

## 1. Architectural Scope and Design Principles

Sistem **Asisten Tugas Citra (ATC)** berfungsi sebagai asisten akademik berbasis bukti nyata (grounded factual writing) yang melayani seluruh domain keilmuan:
- Humaniora dan Kajian Sastra (Textual Analysis, Close Reading, Literature Review)
- Ilmu Sosial, Hukum, dan Bisnis (Legal Analysis, Statutory Interpretation, Case Studies)
- Sains, Teknologi, Rekayasa, dan Matematika / STEM (Algorithm Complexity, Linear Algebra, Inferential Statistics, Classical Electromagnetism)

### Core Architectural Invariants:
1. **Zero New User Flow:** Tidak ada penambahan state machine antarmuka atau wizard baru. UI pipeline tetap 3-stage modular: Stage 1 (Input Problem Statement) -> Stage 2 (Curate Reference Context / Skip Reference Mode) -> Stage 3 (Compile A4 Output).
2. **Zero Route Sprawl:** Tidak ada pembuatan API endpoint baru (seperti `/api/math` atau `/api/calculate`). Pipeline data tetap menggunakan REST endpoints eksisting: `/api/upload-question-file` -> `/api/generate` -> `/api/download/docx`.
3. **Engine-Level Polymorphism:** Adaptasi gaya naskah (esai kritis vs komputasi aljabar bertahap) diselesaikan sepenuhnya di tingkat orkestrasi prompt backend (`tools/question_reader.py` dan `agents/generator.py`).

---

## 2. Root Cause Analysis (Failure Modes)

### Failure Mode 1: Semantic Leakage in Compound Assignment Parsing (`tools/question_reader.py`)
- Pada fungsi `structure_assignment_with_ai` dan regex heuristic analyzer, lembar tugas didekomposisi menjadi dua entitas schema: `question_topic` dan `guidelines`.
- System prompt pemilah memiliki regularisasi reduksi teks yang terlalu agresif, sehingga klausa dependen tugas (sub-questions) seperti *"sertakan kutipan teks pendukung"* atau *"sebutkan karakter pilihanmu beserta alasannya"* mengalami misklasifikasi sebagai petunjuk format dan terlempar ke `guidelines` atau tereduksi.
- Cardinality detector gagal mengidentifikasi penomoran bertingkat saat disajikan dalam format naratif, sehingga `question_count` terisi `null` atau `1`, menyebabkan butir soal kedua terabaikan (dropped section).

### Failure Mode 2: Over-Regularized Paraphrasing Suppressing Direct Verbatim Quotations (`agents/generator.py`)
- Di fungsi penyusun prompt `generate_draft_task_fast` (baris 658–671), blok `citation_rules` menerapkan constraint anti-plagiasi yang terlalu ketat (*"Sumber adalah pendukung argumen, bukan pusat kalimat. Tulis gagasan dengan kalimatmu sendiri..."*).
- Ketiadaan Conditional Quotation Policy menyebabkan model selalu memaksakan parafrase murni `(Author, Year)`, menolak mencetak kutipan langsung di dalam tanda petik ganda (`"..."`), meskipun lembar tugas secara eksplisit menuntut bukti tekstual verbatim.
- Generator mengalami selective attention bias: hanya menjawab kalimat awal suatu butir soal dan mengabaikan sub-pertanyaan evaluatif di bagian akhir kalimat (incomplete sub-question resolution).

### Failure Mode 3: Unstructured Narrative Prose in Exact STEM Computation
- Pada problem domain matematika, statistika, fisika listrik magnet, dan algoritma:
  - Model menghasilkan narasi esai deskriptif tanpa explicit algebraic derivations baris demi baris.
  - Model rentan mengalami arithmetic and sign errors karena ketiadaan protokol Step-by-Step Chain-of-Thought (CoT) dan ketiadaan Self-Consistency / Reverse Substitution Verification.
  - Matriks dan tabel logika disajikan dalam bentuk narasi paragraf acak, bukan Markdown Pipe-Table format.
  - Model mengekspor unescaped raw LaTeX syntax (`\frac`, `$`, `\begin{matrix}`) yang merusak parser `python-docx` dan `reportlab`.

---

## 3. Detailed Engineering Implementation

### A. NLP Parsing Layer (`tools/question_reader.py`)

#### 1. Semantic Boundary Enforcement in `structure_assignment_with_ai`:
Perketat schema contract pada system prompt ekstraksi:
- `question_topic`: Harus mempertahankan Problem Statement seutuhnya, mencakup nomor butir, seluruh sub-pertanyaan majemuk, permintaan bukti kutipan teks, instruksi analisis, teks kasus rujukan, dialog, serta penanda gambar `[[GAMBAR_n]]`. Dilarang melakukan pruning atau pemindahan klausul pertanyaan ke `guidelines`.
- `guidelines`: Dibatasi secara ketat hanya untuk Administrative Metadata di luar materi pengerjaan: batas waktu pengumpulan, sistem skor rubrik dosen, format margin/font, batas total jumlah kata, dan sapaan dokumen.

#### 2. Deterministic Numbering Extraction & Section Cardinality Lock:
- Parsing regex untuk penomoran butir: deteksi pola eksplisit `1.`, `2.`, `3.` atau `a.`, `b.`, `c.` atau `Soal 1:`, `Soal 2:`.
- Enforce invariant: Jika terdeteksi $N$ butir soal mandiri, set `answer_spec.question_count = N` dan set `answer_spec.answer_type = "jawaban_bernomor"` secara deterministik.
- Seluruh teks butir 1 sampai $N$ wajib terpreservasi utuh di dalam `question_topic`.

#### 3. Heuristic STEM / Exact Domain Detection:
- Implementasikan pattern matching token eksakta di `guess_answer_spec` dan `normalize_answer_spec`:
  - Mathematical Operators: `=`, `+`, `-`, `^`, `√`, `∫`, `∑`, `≤`, `≥`, `×`, `÷`, `|`, `matrix`, `[`, `]`.
  - Computer Science & Algorithms: `Big O`, `O(n)`, `kompleksitas`, `algoritma`, `pseudocode`, `rekursif`, `sorting`, `graph`, `tree`, `stack`, `queue`.
  - Linear Algebra: `matriks`, `vektor`, `determinan`, `invers`, `eigenvalue`, `eigenvector`, `Gauss`, `Jordan`, `Cramer`.
  - Statistics: `mean`, `median`, `modus`, `varians`, `standar deviasi`, `distribusi normal`, `regresi`, `hipotesis`, `uji t`, `uji z`, `p-value`.
  - Classical Electromagnetism: `Coulomb`, `Ampere`, `Volt`, `Ohm`, `Farad`, `Tesla`, `Weber`, `Henry`, `Hukum Gauss`, `Hukum Faraday`, `Hukum Ampere`, `Hukum Ohm`, `fluks magnetik`, `medan listrik`, `kapasitor`, `induktor`.
- Jika skor token eksakta melebihi ambang batas, set `answer_spec.answer_type = "hitungan"` atau set boolean flag `is_mathematical = True`.

---

### B. Prompt Orchestration & Synthesis Engine (`agents/generator.py`)

#### 1. Conditional Direct Textual Evidence Policy:
Pada blok `citation_rules`:
- Tambahkan guard clause kondisional:
  Jika input prompt memuat kata kunci bukti tekstual (`kutipan`, `quote`, `quotes`, `kutip`, `textual evidence`, `pasal`, `bunyi teks`, `salin kalimat`) ATAU jika rujukan bertipe bahan bacaan sastra/telaah naskah:
  - Model WAJIB menyertakan kutipan langsung verbatim di dalam tanda petik ganda (`"..."`).
  - Setiap kutipan langsung WAJIB diikuti in-text citation dengan nomor halaman fisik naskah asli: `(Author, Year, hlm. X)`.
  - Di luar tanda petik ganda, model menguraikan analisis kritis dengan kalimat sendiri mengenai korelasi kutipan tersebut dengan fokus pertanyaan.
  - Untuk bagian naskah lain yang tidak menuntut bukti kutipan langsung, pertahankan prinsip parafrase akademis alami.

#### 2. Strict Section Cardinality Invariance:
Pada format `jawaban_bernomor`:
- Setiap butir nomor soal dari lembar tugas WAJIB dipetakan menjadi tepat satu objek seksi mandiri pada array `sections`.
- Attribute `heading` wajib merefleksikan nomor dan topik butir soal, misalnya `1. PERUBAHAN KARAKTER UTAMA` dan `2. ANALISIS TEMA UTAMA`.
- Dilarang keras melakukan merger dua nomor butir ke dalam satu seksi, dan dilarang menghilangkan nomor butir apa pun. Panjang array `sections` wajib konsisten dengan `question_count`.

#### 3. Exhaustive Sub-Question Resolution:
Pada blok `ATURAN MENJAWAB SETIAP BUTIR`:
- Model WAJIB melakukan dekomposisi semantik internal terhadap seluruh sub-pertanyaan yang terkandung dalam satu nomor butir soal (misalnya: sub-komponen alur perubahan, sub-komponen bukti kutipan teks, dan sub-komponen preferensi personal beserta alasannya).
- Seluruh sub-komponen WAJIB dijawab tuntas, terstruktur, dan proporsional di dalam tubuh seksi butir bersangkutan. Dilarang mengabaikan pertanyaan yang terletak di posisi ekor kalimat.

#### 4. Deterministic STEM Computation Protocol:
Ketika `answer_type == "hitungan"` atau flag `is_mathematical == True`:
- **Paragraph Style Invalidation:** Mode esai paragraf naratif otomatis dibatalkan. Seluruh proses komputasi wajib ditulis baris demi baris menggunakan karakter newline nyata (`\n`).
- **Four-Pillar Computation Schema:**
  1. **Diketahui dan Ditanya (Given & Inquired Parameters):** Pemetaan eksplisit seluruh variabel, konstanta, parameter numerik, dan unit satuan. Nyatakan parameter sasaran yang dicari.
  2. **Teorema / Metode / Formula (Governing Equations):** Tuliskan formula matematika standar, teorema formal, atau model komputasi yang dipakai (contoh: `Hukum Ampere: ∮ B · dl = μ₀ I_enc`, `Eliminasi Gauss-Jordan`, `Master Theorem T(n) = aT(n/b) + f(n)`).
  3. **Penurunan Aljabar dan Substitusi Terbuka (Explicit Step-by-Step Derivation):** Tuliskan langkah kalkulasi secara transparan baris demi baris. Substitusikan nilai ke variabel formula, perlihatkan penyederhanaan aljabar, faktorisasi, atau integrasi bertahap. Dilarang melompat langsung ke nilai akhir.
  4. **Jawaban Akhir dan Satuan SI (Final Evaluated Value & SI Units):** Tuliskan nilai akhir secara tegas lengkap dengan satuan metrik resmi atau notasi kompleksitas asimtotik (`O(n log n)`).
- **Self-Consistency & Reverse Substitution Verification:**
  Untuk sistem persamaan linear, optimasi, nilai eigen, atau persamaan aljabar: Model wajib melakukan validasi silang (reverse substitution) di balik layar dengan memasukkan kembali nilai variabel ke persamaan awal untuk memastikan keseimbangan ruas kiri dan ruas kanan ($LHS = RHS$) sebelum merilis hasil akhir.
- **Markdown Pipe-Table Formatting:**
  Matriks aljabar linear, tabel kebenaran gerbang logika, tabel distribusi frekuensi, dan peta Karnaugh wajib diformat baris per baris menggunakan pemisah pipa standar (` | `) dengan header kolom yang jelas. Dilarang menceritakan isi matriks dalam bentuk paragraf naratif.
- **Document-Safe Clean Unicode Math Notation:**
  Gunakan simbol teks Unicode standar: `²`, `³`, `⁴`, `⁻¹`, `√`, `∑`, `∫`, `≤`, `≥`, `×`, `÷`, `π`, `μ`, `ε`, `λ`, `Ω`. DILARANG KERAS menghasilkan sintaks LaTeX mentah seperti `\frac{a}{b}`, `\sqrt{x}`, `\begin{matrix}`, atau enclosing math delimiter `$`.

---

### C. Data Ingestion & Context Layer (`tools/reading_doc_reader.py` & `api/routes.py`)

#### Physical Page Invariance:
- Pada parser naskah PDF bahan bacaan (`read_pdf_file` / `read_reading_doc`), pertahankan penomoran halaman fisik asli dokumen ke dalam metadata `pages_content`:
  ```python
  {"page_number": f"Halaman {page_idx}", "text": page_text}
  ```
- Hindari penamaan partisi maya seperti `Bagian 1` jika dokumen memiliki pagination fisik yang jelas, agar in-text citation `hlm. X` dapat diverifikasi secara presisi terhadap berkas master yang dipegang dosen pemeriksa.

---

## 4. Test Verification Matrix & Quality Assurance

Implementasi wajib diverifikasi dengan unit test otomatis terisolasi:

### Test Suite 1: Compound Parsing & Evidence Validation (`tests/test_multipart_assignment.py`)
- `test_compound_question_extraction`: Validasi bahwa input teks majemuk menghasilkan `question_count == 2`, `question_topic` mempertahankan klausul kutipan dan sub-pertanyaan personal, serta `guidelines` bebas dari materi pertanyaan.
- `test_direct_quotation_synthesis`: Validasi bahwa pembuatan naskah analisis sastra menghasilkan 2 seksi mandiri, memuat kutipan bertanda petik ganda `"..."`, memuat sitasi halaman fisik `hlm.`, dan menuntaskan sub-pertanyaan preferensi personal.

### Test Suite 2: Deterministic STEM Computation (`tests/test_stem_assignment.py`)
- `test_stem_domain_classification`: Validasi klasifikasi otomatis untuk problem domain algoritma, matriks aljabar linear, statistika, dan fisika listrik magnet.
- `test_stem_four_pillar_structure`: Validasi bahwa keluaran komputasi memuat token `Diketahui`, `Ditanya`, penurunan aljabar baris demi baris via `\n`, matriks berformat pemisah pipa `|`, serta 100% bebas dari unescaped LaTeX delimiter (`\frac` atau `$`).

### Zero-Regression Mandate:
Jalankan seluruh regression test suite:
```bash
pytest --ignore=tests/test_browser_ui.py
```
Seluruh unit test eksisting (minimal 89 tests) wajib tetap berstatus pass hijau tanpa regresi.

---

## 5. Formal Prompt Penugasan untuk Claude (Ready to Copy-Paste)

Gunakan blok instruksi formal berikut saat mendelegasikan pengerjaan ke Claude:

```markdown
# Engineering Task: Multi-Part Question Resolution, Direct Textual Evidence, and Deterministic STEM Computation

## Objective
Implement comprehensive enhancements in `tools/question_reader.py`, `agents/generator.py`, and `tools/reading_doc_reader.py` within the Asisten Tugas Citra codebase. Ensure robust support for compound multi-part assignments, conditional direct verbatim quotations with physical page citations, and deterministic step-by-step STEM computations (Algorithms, Linear Algebra, Statistics, Electromagnetism) without introducing new UI flows or new API endpoints.

## Implementation Targets

1. `tools/question_reader.py`:
   - Refactor `structure_assignment_with_ai` system prompt: Enforce semantic boundary where `question_topic` strictly preserves all problem statements, sub-questions, evidence requirements, and data tables without pruning into `guidelines`.
   - Implement deterministic numbering parsing to lock `answer_spec.question_count` and enforce `answer_type = "jawaban_bernomor"`.
   - Add regex/token heuristic classifier for STEM domains (operators, algorithms, matrices, statistics, electromagnetism) to set `answer_type = "hitungan"`.

2. `agents/generator.py`:
   - Implement Conditional Textual Evidence Policy in `citation_rules`: Require direct verbatim quotations in double quotes `"..."` followed by physical page citations `(Author, Year, hlm. X)` when evidence is requested or when analyzing reading materials.
   - Enforce Section Cardinality Invariance: Ensure array `sections` contains exactly one dedicated heading per numbered question item, matching `question_count`.
   - Enforce Exhaustive Sub-Question Resolution: Ensure all nested sub-questions within a single item are addressed systematically.
   - Implement Deterministic STEM Protocol: Invalidate narrative paragraph mode; enforce Four-Pillar CoT schema (Diketahui & Ditanya, Governing Formula, Step-by-Step Algebraic Derivation via `\n`, Final Evaluated Value & SI Units); enforce reverse substitution verification; enforce Markdown pipe-table formatting for matrices/logic tables; and restrict mathematical notation to clean Unicode, strictly disallowing unescaped raw LaTeX (`\frac`, `$`).

3. `tools/reading_doc_reader.py` and `api/routes.py`:
   - Preserve physical document page indices (`Halaman X`) in `pages_content` chunk metadata.

## Verification & QA
- Create `tests/test_multipart_assignment.py` and `tests/test_stem_assignment.py` covering all aforementioned assertions.
- Verify zero regression: Run `pytest --ignore=tests/test_browser_ui.py` and ensure 100% green pass.
- Commit with Conventional Commits format:
  `feat: implement multi-part assignment resolution, direct textual evidence, and deterministic stem computation`
```
