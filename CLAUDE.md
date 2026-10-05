# Panduan Operasional Claude (CLAUDE.md)

Dokumen ini adalah instruksi operasional resmi dan kontrak kerja untuk Claude saat bekerja di direktori repositori ini. Patuhi seluruh batasan teknis dan alur eksekusi tanpa kompromi.

---

## 1. Identitas Proyek dan Lingkungan Kerja
- **Nama Aplikasi:** Asisten Tugas Citra (ATC)
- **Bentuk Aplikasi:** Aplikasi desktop Windows dengan shell Electron di folder `desktop/`. Electron menjalankan backend `run_app.py` sebagai proses terpisah, versi rilis memakai `AsistenTugasCitraServer.exe` hasil PyInstaller onedir. Build installer: `cd desktop && npm run dist`.
- **Frontend Stack:** Single Page Application berbasis HTML semantik di `static/index.html`, Tailwind CSS via CDN, font Plus Jakarta Sans dan Newsreader serif, serta Vanilla JavaScript di `static/app.js`.
- **Backend Stack:** FastAPI lokal di `127.0.0.1` dengan Python 3.11+.
- **Penyimpanan Profil Webview:** Profil dan `localStorage` tersimpan permanen di `%LOCALAPPDATA%\AsistenTugasCitra\electron`.

---

## 2. Kitab Suci Utama (Single Source of Truth)
Sebelum menulis satu baris kode pun, Claude WAJIB membaca dan mematuhi dua dokumen berikut:
1. `plans/bahan-bacaan-dosen.md`: Cetak biru arsitektur tiga jalur tugas, spesifikasi endpoint, desain antarmuka menyeluruh (Academic Studio Modern), dan checklist pengerjaan.
2. `DESIGN.md`: Aturan token desain tiga lapis (Stone, Emerald, Status, Semantic, Component tokens), tipografi, dan kontras WCAG.

---

## 3. Pemanfaatan Wajib Context7 MCP
Claude WAJIB memanfaatkan MCP server `context7` sebelum menulis atau memodifikasi kode:
- Panggil `resolve-library-id` dan `query-docs` untuk memeriksa utilitas Tailwind CSS, tata letak grid, dan sintaks pseudo-class agar tidak berhalusinasi memakai class yang tidak didukung CDN.
- Gunakan `context7` untuk mengambil referensi path SVG semantik modern (seperti Lucide icons) agar tampilan tombol dan kartu konsisten.
- Gunakan `context7` untuk memeriksa sintaks FastAPI `UploadFile` atau pustaka `pypdf` jika diperlukan.

---

## 4. Batasan Lingkup Kerja (Strict Boundaries)

### Status Fondasi Backend (Sudah Selesai Dikerjakan dan Teruji):
- **Persistensi Tugas ke Disk:** Modul `tools/task_store.py` sudah aktif menyimpan dan memuat tugas dari `storage/tasks/{task_id}.json`. Data tugas aman dan tidak hilang saat aplikasi ditutup.
- **Robust JSON Recovery:** Fungsi `robust_json_dict_parse` di `agents/generator.py` sudah menangani dan memulihkan respons JSON yang terbungkus markdown atau berkarakter kontrol liar.
- **Pembersih Sampah Berkas:** Modul `tools/storage_cleaner.py` sudah aktif di `api/main.py` membersihkan berkas usang.
- **Verifikasi Test:** Seluruh 73 pengujian unit di `pytest` telah lolos berstatus hijau.

### Fokus Utama Penugasan Claude (In Scope):
- Perombakan total antarmuka (Whole New Redesign) di `static/index.html` dan `static/app.js` bergaya Academic Studio Modern.
- Tiga jalur adaptif (Forum Diskusi, Bahan Dosen, Riset Jurnal).
- Redesign Tahap 1 dengan 3 kartu pilihan interaktif, tab unggah atau ketik soal, dan tombol aksi dinamis.
- Penerapan 6 prinsip frontend inti: Visual Hierarchy, Design Tokens, Progressive Disclosure, Information Architecture, Separation of Concerns di JavaScript, dan Desktop-First Responsive.
- Penerapan Multi-State Feedback (idle, uploading, skeleton shimmer, live progress 4 tahap, success preview, error rate-limited).
- Penerapan Defensive UI (auto-draft teks soal ke localStorage, konfirmasi sebelum menimpa teks).
- Modul pemecah teks naskah panjang di `tools/content_chunker.py` dan pembaca berkas di `tools/reading_doc_reader.py`.
- Endpoint ekstraksi lokal `POST /api/parse-reading-doc` untuk PDF, DOCX, dan TXT tanpa menyedot kuota Gemini.
- Endpoint penyimpanan bahan bacaan mandiri `POST /api/manual-module` dengan chunking paragraf cerdas.
- Penyempurnaan prompt di `agents/generator.py` agar mendukung nada bahasa mahasiswa dan sitasi naskah dosen yang bersih dari label kaku.
- Perapian daftar pustaka APA di `exporters/docx_builder.py` dan `exporters/pdf_builder.py`.

### Yang DILARANG KERAS Dikerjakan (Out of Scope):
- DILARANG menambah framework frontend seperti React, Vue, atau Svelte. Wajib tetap Vanilla JS dan Tailwind CDN.
- DILARANG memasang bundler npm seperti Vite, Webpack, atau Tailwind CLI.
- DILARANG memecah folder frontend ala Atomic Design atau memasang tooling Storybook.
- DILARANG memasang database eksternal seperti PostgreSQL atau vector database (Chroma, Pinecone). Gunakan memori lokal.
- DILARANG mengganti title bar native Electron `titleBarOverlay` di `desktop/main.js` dengan tombol jendela buatan sendiri.
- DILARANG menambah fitur ekstraksi gambar, lightbox, atau manipulasi gambar yang tidak relevan dengan naskah teks akademis.

### Standar Keamanan Pragmatis:
- **Kerahasiaan Kunci API:** Kunci GEMINI_API_KEY wajib tetap di backend lewat berkas .env. Dilarang membocorkan kunci ke response JSON, DOM frontend, atau dokumen ekspor.
- **Validasi Unggah Berkas:** Endpoint `/api/parse-reading-doc` wajib membatasi ekstensi hanya berkas dokumen `.pdf`, `.docx`, `.txt`, `.md`, membatasi ukuran maksimal 20MB, dan menggunakan sanitasi nama berkas untuk mencegah path traversal.
- **Isolasi Jaringan Loopback:** Server FastAPI wajib selalu terikat ke alamat `127.0.0.1`, dilarang mengikat ke `0.0.0.0`.
- **Bebas Otentikasi Berlebihan:** Dilarang menambah sistem login, OAuth, atau JWT token karena ini aplikasi desktop lokal satu pengguna.

---

## 5. Urutan Eksekusi Bertahap (Step by Step)
Claude wajib mengeksekusi secara berurutan sesuai checklist di `plans/bahan-bacaan-dosen.md`:
1. Riset dokumentasi via Context7 MCP.
2. Update skema Pydantic di `api/schemas.py`.
3. Buat pembaca dokumen di `tools/reading_doc_reader.py` dan pemecah teks di `tools/content_chunker.py`.
4. Pasang endpoint baru di `api/routes.py`.
5. Sesuaikan prompt di `agents/generator.py` dan exporter di `exporters/`.
6. Rombak total struktur HTML di `static/index.html` dan logika di `static/app.js`.
7. Poles transisi dan token CSS di `static/theme.css`.
8. Jalankan seluruh pengujian otomatis dengan perintah terminal `pytest` dan pastikan seluruh test berstatus lolos (passed).

---

## 6. Standar Verifikasi Mandiri dan Commit
- Sebelum menyatakan pekerjaan selesai, jalankan `pytest` di terminal dan pastikan tidak ada galat.
- Buat komit git menggunakan format Conventional Commits, misalnya:
  `feat: redesign total antarmuka academic studio dan alur bahan dosen`
