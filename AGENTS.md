# AGENTS.md - Konteks dan Aturan Proyek Asisten Tugas Citra

## 1. Identitas dan Tujuan Proyek
- **Nama Proyek:** Asisten Tugas Citra
- **Tujuan:** Membangun asisten penulisan tugas kuliah berbasis bukti nyata. Sistem mencari jurnal ilmiah dari OpenAlex, mengunduh berkas naskah asli, membedah teks dengan akurat, merangkai pembahasan akademis menggunakan otak Gemini tanpa halusinasi, dan langsung mencetak dokumen A4 siap kumpul ke format docx dan pdf. Mendukung tiga format luwes: Makalah Ilmiah (Bab I, II, III), Jawaban Diskusi Mengalir (Tanpa Bab), dan Jawaban Tugas Bernomor (1, 2, dst).

## 2. Tech Stack dan Ekosistem
- **Bahasa Pemrograman:** Python 3.11+
- **Kerangka Utama:** FastAPI untuk backend API
- **Orkestrasi LLM:** google-genai SDK resmi untuk Google AI Studio Gemini API
- **Pengunduh dan HTTP Client:** httpx
- **Ekstraktor Dokumen:** pypdf
- **Penyusun Dokumen Word:** python-docx
- **Penyusun Dokumen Cetak:** reportlab
- **Antarmuka Pengguna:** Static HTML, Tailwind CSS via CDN, Vanilla JavaScript
- **Validasi Data:** pydantic
- **Manajemen Environment:** python-dotenv
- **Testing:** pytest
- **Catatan untuk AI:** Gunakan ekosistem ini secara konsisten. Dilarang menambah pustaka eksternal yang memerlukan kompilator sistem tambahan di Windows.

## 3. Struktur Folder
Patuhi struktur arsitektur modular berikut. Jangan membuat file di luar struktur ini:
- `/agents`: Logika orkestrasi Gemini, prompt generator akademis, dan guardrails sitasi.
- `/tools`: Modul teknis terisolasi (academic_search.py, pdf_downloader.py, pdf_parser.py).
- `/exporters`: Modul perakit berkas keluaran (docx_builder.py, pdf_builder.py).
- `/api`: Rute endpoint FastAPI dan skema Pydantic.
- `/static`: Halaman antarmuka web tiga langkah.
- `/storage`: Penyimpanan sementara berkas naskah unduhan dan hasil render.
- `/tests`: Skrip pengujian otomatis.

## 4. Aturan Coding dan Kolaborasi
- **Gaya Penulisan:** Terapkan prinsip Clean Code. Gunakan Type Hinting secara disiplin di semua fungsi Python. Terapkan fail-fast guard clauses di awal fungsi.
- **Error Handling:** Semua pemanggilan API eksternal dan download naskah wajib dibungkus try-except dengan timeout terukur.
- **Aturan Wajib Anti Halusinasi:** Model bahasa dilarang keras membuat klaim atau menulis daftar pustaka jika naskah aslinya tidak berhasil diunduh dan dibaca di direktori storage.
- **Standar Gaya Bahasa Mahasiswa Tulen:** Wajib menggunakan nada tulisan mahasiswa yang memahami materi secara membumi. Dilarang menggunakan sapaan pembuka (Halo Tutor, Selamat pagi), dilarang menggunakan penutup klise (Demikian, In conclusion), dilarang menggunakan bullet points tebal yang berlebihan, dan dilarang memakai kata klise AI seperti krusial, esensial, ranah, delve, crucial, multifaceted, pivotal, serta secara keseluruhan.

## 5. Daftar Fitur dan Status
- [ ] Setup integrasi Gemini API dan validasi API Key di file env.
- [ ] Modul pencarian OpenAlex dan pengunduh naskah terbuka.
- [ ] Modul ekstraksi teks per halaman dari berkas naskah.
- [ ] Agen perakit draf naskah tugas berbasis sitasi halaman nyata.
- [ ] Modul eksportir dokumen docx dan pdf standar A4.
- [ ] Antarmuka web pengguna tiga langkah.

## 6. Testing dan Batasan
- **Testing:** Setiap modul di folder tools wajib memiliki unit test terisolasi sebelum diintegrasikan ke agen.
- **Larangan 1:** Jangan pernah melakukan hardcode API Key, token, atau kredensial di dalam kode. Selalu gunakan file .env.
- **Larangan 2:** Jangan meloloskan sitasi yang tidak memiliki bukti nomor halaman dari berkas naskah asli.

## 7. Aturan Commit
Setiap kali selesai membuat fitur baru, perbaikan bug, atau penambahan kode yang lolos pengujian, langsung siapkan komit dengan format Conventional Commits.
- Contoh: `feat: implementasi pencarian openalex dan downloader pdf`
- Contoh: `fix: penanganan timeout saat unduh berkas naskah`
