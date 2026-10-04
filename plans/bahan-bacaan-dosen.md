# Cetak Biru Eksekusi: Redesign Total Antarmuka dan Alur Tugas Universal

Dokumen ini adalah cetak biru teknis resmi untuk dikerjakan oleh Claude. Berisi instruksi perombakan total desain antarmuka pengguna (whole new frontend redesign) dan penambahan alur tugas universal. Dilarang menambah framework berat di luar Vanilla JS dan Tailwind CSS.

---

## 1. Konteks Runtime dan Lingkungan Eksekusi

1. **Aplikasi Desktop PyWebView:** Aplikasi ini berjalan di desktop Windows dibungkus menggunakan `pywebview` melalui file `run_app.py`.
2. **Frontend Stack:** Single Page Application berbasis HTML semantik, Tailwind CSS CDN, dan Vanilla JavaScript murni di folder `static/`.
3. **Backend Stack:** FastAPI lokal di alamat loopback `127.0.0.1`.
4. **Penyimpanan Permanen:** Profil pengguna dan `localStorage` tersimpan permanen di direktori `%LOCALAPPDATA%\AsistenTugasCitra\webview`. Nilai nama, NIM, dan preferensi gaya bahasa aman tersimpan antar sesi aplikasi.

### 1.1 Pemanfaatan Context7 MCP untuk Dokumentasi dan Komponen UI
Claude DIWAJIBKAN memanfaatkan alat **Context7 MCP** (`resolve-library-id` dan `query-docs`) untuk mengambil rujukan dokumentasi resmi secara presisi:
- **Tailwind CSS:** Gunakan Context7 untuk memastikan utilitas class warna, grid, animasi transisi, dan state pseudo-class (`hover:`, `active:`, `focus-visible:`, `dark:`) valid tanpa mengira-ngira class yang tidak ada di versi Tailwind CDN.
- **Ikonografi Lucide atau SVG Semantik:** Cari referensi bentuk SVG ikon modern via Context7 agar ikon di setiap kartu mode dan tombol aksi terlihat konsisten, presisi, dan bukan ikon generik asal buat.
- **FastAPI dan Pypdf:** Gunakan Context7 jika membutuhkan verifikasi sintaks terkini penanganan `UploadFile`, streaming status, atau ekstraksi `pypdf.PdfReader`.
- **Aturan Alur:** Selesaikan pembacaan dokumentasi via Context7 sebelum menulis komponen UI atau logika endpoint agar kode yang dihasilkan bebas dari galat sintaks usang.

---

## 2. Arahan Desain Baru: Academic Studio Modern (Anti AI Slop)

### 2.1 Konsep dan Karakter Visual
Tinggalkan tata letak kartu generik yang kaku. Bangun antarmuka bergaya **Academic Studio Modern** yang tenang, percaya diri, dan berwibawa:
- **Pondasi Warna:** Nuansa Warm Stone alami (`stone-50` hingga `stone-950`), aksen Deep Obsidian untuk aksi utama, serta Emerald tegas untuk verifikasi naskah.
- **Tipografi:** Plus Jakarta Sans untuk antarmuka interaktif dan Newsreader serif untuk pratinjau lembar naskah A4.
- **Bebas Elemen Norak:** Dilarang memakai gradien ungu kebiruan murahan, bayangan blur berlebihan, atau teks placeholder yang membingungkan.
- **Dukungan Penuh Dua Tema:** Tampilan terang dan gelap wajib terpadu harmonis tanpa ada teks abu-abu yang tenggelam.

### 2.2 Aturan Mikrointeraksi dan Noticeable Hover
Seluruh elemen interaktif wajib memberikan umpan balik taktil seketika:
- **Kontras Hover:** Perubahan warna latar yang tegas dalam durasi 100 sampai 150 milidetik (`transition-all duration-150 ease-out`).
- **Elevasi Halus:** Efek angkat tipis saat diarahkan kursor (`hover:-translate-y-0.5 hover:shadow-md`).
- **Umpan Balik Tekan:** Efek mengecil taktil saat diklik (`active:translate-y-0 active:scale-[0.98]`).
- **Kursor Jelas:** Wajib menyertakan `cursor-pointer` pada seluruh tombol, kartu opsi, badge yang bisa diklik, dan tab navigasi.
- **Fokus Aksesibilitas:** Ring fokus keyboard yang tegas (`focus-visible:ring-2 focus-visible:ring-stone-900 dark:focus-visible:ring-stone-100`).

### 2.3 Prinsip Rekayasa Frontend dan UX
Penerapan arsitektur antarmuka difokuskan penuh pada prinsip berikut:
- **Visual Hierarchy:** Kontras ukuran teks, bobot warna, dan spasi yang membimbing mata pengguna dari input soal, ke kartu mode, lalu ke tombol aksi utama tanpa kebingungan.
- **Design Tokens:** Gunakan token CSS variabel dari `DESIGN.md` (`--primitive-...`, `--color-...`, `--comp-...`) agar harmoni warna tema terang dan gelap tetap konsisten.
- **Progressive Disclosure:** Tampilkan informasi bertahap. Sembunyikan setelan lanjutan seperti gaya bahasa, identitas mahasiswa, dan format luaran di dalam panel lipat atau langkah yang relevan agar layar awal tetap bersih.
- **Information Architecture dan User Flow:** Struktur navigasi terbagi tegas ke dalam tiga jalur adaptif yang tidak saling tumpang tindih.
- **Separation of Concerns di JavaScript:** Pisahkan struktur kode di `static/app.js` menjadi tiga bagian terisolasi: objek State Aplikasi, fungsi pemanggil API (HTTP service), dan fungsi pembaruan DOM (UI render). Dilarang menumpuk pemanggilan API langsung di dalam event listener.
- **Desktop-First Responsive:** Utamakan kenyamanan layar laptop dan komputer meja mulai dari lebar 1024 piksel ke atas, dengan tata letak yang tetap adaptif jika ukuran jendela diperkecil.
- **Multi-State Feedback:** Definisikan status visual komponen secara eksplisit yaitu idle, uploading, parsing skeleton shimmer, live progress pipeline, success preview, dan error rate-limited agar pengguna selalu tahu proses di latar belakang sedang bekerja.
- **Defensive UI:** Lindungi data ketikan manual mahasiswa dengan menyimpan draf teks soal di localStorage serta menampilkan dialog konfirmasi sebelum menimpa teks yang sudah ada jika pengguna mengunggah berkas baru tanpa sengaja.

---

## 3. Spesifikasi Komponen Desain Menyeluruh (Whole New UI)

### 3.1 Header Aplikasi dan Kontrol Jendela Desktop
- **Identitas Studio:** Logo ringkas ATC dengan lencana status API Gemini yang memiliki indikator lampu bernapas lembut (pulsing emerald saat siap, amber saat jeda).
- **Pengalih Tema:** Tombol pengalih tema bulat ramping dengan transisi rotasi halus antara ikon matahari dan bulan.
- **Kontrol Jendela Tanpa Bingkai:** Integrasi tombol perkecil, perbesar, dan tutup jendela yang menyatu rapi di pojok kanan atas khusus runtime pywebview.

### 3.2 Stepper Timeline Tiga Tahap yang Interaktif
Ganti tab kotak kaku dengan timeline horizontal modern yang elegan:
- **Tahap 1:** Masukkan Soal dan Mode
- **Tahap 2:** Kurasi Sumber Rujukan
- **Tahap 3:** Studio Naskah dan Cetak Dokumen
- **Perilaku:** Tampilkan nomor melingkar dengan garis penghubung. Tahap yang sedang aktif diberi cincin obsidian menyala lembut. Tahap yang sudah selesai diberi ikon centang emerald dan dapat diklik untuk kembali jika pengguna ingin memeriksa input sebelumnya.

### 3.3 Redesign Total Tahap 1: Masukkan Soal dan Konfigurasi Cerdas
Buat pengalaman pengguna yang terarah tanpa rasa bingung melalui 4 seksi yang mengalir alami:

#### Seksi 1: Masukkan Soal Tugas
- **Dual Tab Interaktif:** Sediakan pemilih tab "Ketik Langsung" dan "Unggah Berkas Soal".
- **Area Unggah Berkas:** Dropzone lapang dengan ikon dokumen, teks panduan seret berkas, serta tombol unggah yang mencolok.
- **Pratinjau Soal:** Jika berkas diunggah, tampilkan cuplikan teks soal dalam kontainer rapi dengan lencana jumlah karakter dan tombol ganti berkas.

#### Seksi 2: Pemilih Tiga Jalur Pengerjaan (3 Kartu Mode Interaktif)
Ganti formulir bertumpuk dengan 3 kartu pilihan radio visual:
1. **Kartu Jalur A: Diskusi Forum LMS**
   - Ikon: Balon percakapan dua arah
   - Judul: Forum Diskusi Kampus
   - Deskripsi: Jawaban mengalir lugas tanpa struktur bab. Langsung siap disalin ke forum diskusi e-learning.
   - Perilaku Alur: Memilih kartu ini membuat tombol aksi di bawah langsung mengarah ke proses pembuatan naskah di Tahap 3 tanpa melewati pencarian jurnal.
2. **Kartu Jalur B: Bahan Dosen dan Modul Kampus**
   - Ikon: Tumpukan buku atau naskah kuliah
   - Judul: Bahan Dosen atau Modul
   - Deskripsi: Bedah cerpen, bab buku, modul kuliah UT, atau lembar materi yang diberikan pengajar.
   - Perilaku Alur: Tombol aksi di bawah mengarahkan ke Tahap 2 bagian kurasi bahan bacaan mandiri.
3. **Kartu Jalur C: Riset Jurnal Ilmiah Terbuka**
   - Ikon: Mikroskop riset atau arsip ilmiah
   - Judul: Riset Jurnal Ilmiah
   - Deskripsi: Cari artikel ilmiah bereputasi dari repositori OpenAlex untuk tugas makalah resmi.
   - Perilaku Alur: Tombol aksi di bawah mengarahkan ke Tahap 2 bagian pencarian OpenAlex.

#### Seksi 3: Pengaturan Gaya dan Identitas Mahasiswa
Kemas dalam panel lipat yang rapi dengan setelan bawaan cerdas:
- **Gaya Bahasa Mahasiswa:** 5 pilihan gaya suara dengan tombol chip radio yang elegan:
  1. Opini Reflektif Mahasiswa (gaya "Menurut saya...", cocok untuk forum diskusi)
  2. Akademis Formal Lugas (bahasa ilmiah standar tugas kuliah)
  3. Analisis Kritis Tajam (komparasi mendalam teori dan kasus)
  4. Eksploratif Mengalir (gaya esai bebas bertutur)
  5. Surat Personal atau Komunikasi (tugas korespondensi praktis)
  - Wajib disimpan otomatis ke `localStorage` dengan kunci `atc-user-tone`.
- **Identitas Mahasiswa:** Kolom Nama, NIM, dan Mata Kuliah dengan lencana "Tersimpan Otomatis" di `localStorage` (`atc-student-name`, `atc-student-id`).
- **Format Luaran Dokumen:** Pilihan format Makalah Ilmiah Bab I sampai III, Jawaban Bernomor, atau Esai Tanpa Bab.

#### Seksi 4: Tombol Aksi Utama Dinamis
Tombol lebar dengan kontras tinggi yang berada di bagian bawah:
- Teks tombol menyesuaikan mode: "Tulis Jawaban Diskusi Sekarang", "Lanjut: Masukkan Bahan Bacaan", atau "Lanjut: Cari Jurnal Ilmiah".
- Disertai petunjuk langkah kecil di bawah tombol agar pengguna tahu persis ke mana alur membawanya.

---

### 3.4 Redesign Total Tahap 2: Studio Kurasi Sumber dan Rujukan
Tata letak adaptif sesuai mode yang aktif:

#### Tampilan Jalur Bahan Bacaan Dosen (Mode B):
- **Dropzone Bahan Khusus:** Area unggah berkas cerpen, PDF buku, atau naskah tugas.
- **Ekstraksi Teks Lokal Kilat:** Tampilkan bilah indikator membaca dokumen lokal tanpa menyedot kuota Gemini.
- **Kartu Metadata Bebas:** Formulir teks bebas untuk Judul Naskah, Penulis, Tahun Terbit, dan Nama Sumber atau Penerbit. Dilarang memaksa label kategori kaku seperti universitas terbuka jika bahannya adalah cerpen sastra umum.
- **Pratinjau Potongan Naskah:** Area baca cuplikan naskah berpenomoran bagian yang dapat diperiksa mahasiswa sebelum mulai menyusun draf.

#### Tampilan Jalur Jurnal Terbuka (Mode C):
- **Bilah Pencarian Cepat:** Input pencarian jurnal dengan kata kunci otomatis dari soal.
- **Kartu Paper Ilmiah Modern:** Kartu hasil pencarian menampilkan judul tebal, penulis, tahun, nama jurnal, lencana akses terbuka (Open Access), serta tombol pratinjau abstrak naskah.
- **Pilihan Seleksi:** Checkbox elegan dengan lencana penghitung rujukan terpilih di bagian bawah.

---

### 3.5 Redesign Total Tahap 3: Studio Naskah dan Pratinjau Dokumen Cetak

#### Pelacak Kemajuan Pembuatan Naskah (Real-Time Pipeline)
Ganti animasi putar biasa dengan pelacak kemajuan empat tahap yang transparan:
1. Membaca soal dan membedah konteks tugas
2. Memeriksa bahan rujukan dan ekstraksi bukti sitasi
3. Merangkai pembahasan akademis
4. Memvalidasi daftar pustaka dan format naskah

#### Pratinjau Lembar A4 Realistis
- **Kanvas Kertas A4:** Kontainer naskah berlatar putih bersih dengan bayangan lembaran kertas nyata (`shadow-lg border border-stone-200`).
- **Tipografi Newsreader:** Teks naskah menggunakan huruf serif Newsreader berukuran proporsional, jarak baris 1.7, indentasi alinea teratur, dan penataan judul bab yang berwibawa.
- **Kutipan dan Sitasi Jelas:** Setiap kutipan sitasi bergaris bawah halus atau lencana penanda yang dapat diklik untuk melihat sumber aslinya.

#### Bilah Aksi Cepat (Floating Action Bar)
Sediakan bilah aksi melayang yang mudah dijangkau di bagian bawah atau atas pratinjau:
- **Tombol Unduh Word (.docx):** Unduh berkas format A4 dengan styling rapi.
- **Tombol Unduh PDF (.pdf):** Unduh berkas cetak langsung dengan nomor halaman.
- **Tombol Salin Seluruh Teks:** Salin naskah langsung ke clipboard dengan umpan balik toast notifikasi "Naskah berhasil disalin".
- **Tombol Buat Tugas Baru:** Reset form dan kembali ke awal dengan modal konfirmasi ramah.

---

### 3.6 Empat Status UI Wajib (State Contract)
Pastikan setiap komponen memiliki empat status antarmuka yang terdefinisi rapi:
1. **Loading Skeleton:** Animasi shimmer halus pada kontainer kartu saat naskah atau pencarian sedang diproses.
2. **Empty State:** Ilustrasi grafis minimalis dan teks informatif saat belum ada rujukan yang dimasukkan atau daftar hasil pencarian kosong.
3. **Error State:** Banner notifikasi berwarna merah bata lembut (`bg-rose-50 border-rose-200 text-rose-900`) dengan bahasa manusiawi yang menerangkan akar kendala dan tombol coba lagi.
4. **Success State:** Umpan balik visual hijau emerald saat berkas berhasil diunggah atau naskah selesai disusun.

---

## 4. Arsitektur Backend dan Daftar Endpoint

### 4.1 Endpoint: Ekstraksi Berkas Bacaan Dosen
- **Method:** `POST`
- **Path:** `/api/parse-reading-doc`
- **Content-Type:** `multipart/form-data`
- **Parameter:** `file` (UploadFile, mendukung `.pdf`, `.docx`, `.txt`, `.md`, batas 20MB)
- **Logika:**
  - Jika file TXT atau MD: Dekode teks langsung secara lokal.
  - Jika file DOCX: Ekstrak paragraf dan tabel menggunakan pustaka `python-docx`.
  - Jika file PDF: Ekstrak teks halaman menggunakan `pypdf.PdfReader`. Jika teks kurang dari 50 karakter (hasil scan), panggil cadangan Gemini OCR.
- **Luaran:** JSON memuat `success`, `filename`, `text`, `char_count`, dan `message`.

### 4.2 Endpoint: Simpan Bahan Bacaan Mandiri
- **Method:** `POST`
- **Path:** `/api/manual-module`
- **Content-Type:** `application/json`
- **Model Request:**
  - `module_title`: string wajib
  - `author`: string opsional
  - `year`: integer opsional
  - `publisher_or_venue`: string opsional (teks bebas penerbit atau nama majalah)
  - `page_or_ref`: string opsional
  - `content_text`: string naskah wajib
- **Logika:**
  - Jika judul mengandung kode mata kuliah UT, tandai `is_ut_bmp: true`. Jika bukan, tandai `is_ut_bmp: false` dan jangan beri label Universitas Terbuka.
  - Pecah teks panjang menjadi kumpulan segmen `pages_content` menggunakan pemecah paragraf cerdas.
  - Simpan naskah ke penyimpanan sementara memori `CACHED_PAPERS[id]`.
- **Luaran:** JSON format `PaperItem`.

### 4.3 Endpoint: Generator Naskah Akademis
- **Method:** `POST`
- **Path:** `/api/generate`
- **Logika:**
  - Naikkan batas potongan teks naskah dosen di prompt menjadi 3.000 karakter per bagian agar isi cerpen atau buku terbaca utuh.
  - Terapkan format sitasi APA murni `(Penulis, Tahun)` tanpa menyisipkan nomor bagian sistem.
  - Dukung gaya bahasa dinamis sesuai pilihan `tone` dari pengguna.

---

## 5. Urutan Pengerjaan Claude (Step by Step Execution)

Claude wajib mengikuti urutan pengerjaan berkas berikut agar rapi dan tidak merusak fitur yang sudah ada:

0. [ ] **Eksplorasi Context7 MCP:** Manfaatkan `context7` MCP tool (`resolve-library-id` dan `query-docs`) untuk mengambil rujukan utilitas class Tailwind CSS, pola ikon SVG Lucide, dan struktur FastAPI sebelum mulai ngoding.
1. [ ] **Skema Data:** Perbarui `api/schemas.py` untuk mendukung skema bahan bacaan mandiri dan gaya bahasa modular.
2. [ ] **Modul Pemecah Teks:** Buat `tools/content_chunker.py` untuk memotong teks panjang berbasis paragraf dan menghitung relevansi dengan pertanyaan soal.
3. [ ] **Modul Pembaca Berkas:** Buat `tools/reading_doc_reader.py` untuk ekstraksi lokal file PDF, DOCX, dan TXT.
4. [ ] **Rute API Backend:** Daftarkan endpoint `/api/parse-reading-doc` dan perbarui `/api/manual-module` di `api/routes.py`.
5. [ ] **Prompt Generator:** Sempurnakan `agents/generator.py` agar prompt mendukung gaya bahasa dinamis dan pembacaan bahan non-UT yang bersih dari label kaku.
6. [ ] **Eksportir Dokumen:** Sesuaikan `exporters/docx_builder.py` dan `exporters/pdf_builder.py` agar daftar pustaka rapi saat nama penerbit kosong.
7. [ ] **Redesign Total Tampilan HTML:** Rombak total struktur `static/index.html` sesuai spesifikasi Academic Studio Modern (Header, Stepper Timeline, Tahap 1, Tahap 2, Tahap 3, Kanvas A4, Modal Status).
8. [ ] **Logika Frontend dan Reaktivitas:** Tulis ulang logika `static/app.js` untuk mengelola tiga jalur navigasi, interaksi kartu mode, persistensi localStorage, ekstraksi berkas, dan umpan balik mikrointeraksi.
9. [ ] **Gaya CSS dan Tema:** Pastikan `static/theme.css` mendukung transisi halus, warna Warm Stone, dan styling lembar kertas A4 pratinjau.
10. [ ] **Pengujian Mandiri:** Jalankan suite pengujian `pytest` dan pastikan seluruh endpoint dan alur berjalan sempurna tanpa galat.
