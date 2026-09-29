# DESIGN SYSTEM SPECIFICATION: ASISTEN TUGAS CITRA (ATC)

## 1. Identitas Visual & Prinsip Desain
- **Karakter Visual:** Modern Academic Minimalist, hangat, terpercaya, bebas dari gaya generik AI.
- **Tipografi Utama:** Plus Jakarta Sans untuk UI antarmuka dan kontrol interaktif.
- **Tipografi Dokumen:** Newsreader (Serif) untuk naskah karya ilmiah dan pratinjau A4.
- **Pondasi Warna:** Nuansa Warm Stone yang nyaman di mata untuk sesi belajar panjang, dipadukan dengan aksen Deep Obsidian dan Emerald untuk verifikasi akademik.

---

## 2. Arsitektur Token Tiga Lapis (Three-Layer Token Architecture)

### Lapisan 1: Primitive Tokens (Nilai Mentah)

#### Stone Palette (Netral Alami)
- `--primitive-stone-50`: `#fafaf9`
- `--primitive-stone-100`: `#f5f5f4`
- `--primitive-stone-200`: `#e7e5e4`
- `--primitive-stone-300`: `#d6d3d1`
- `--primitive-stone-400`: `#a8a29e`
- `--primitive-stone-500`: `#78716c`
- `--primitive-stone-600`: `#57534e`
- `--primitive-stone-700`: `#44403c`
- `--primitive-stone-800`: `#292524`
- `--primitive-stone-900`: `#1c1917`
- `--primitive-stone-950`: `#0c0a09`

#### Emerald Palette (Verifikasi & Modul Kampus)
- `--primitive-emerald-50`: `#ecfdf5`
- `--primitive-emerald-100`: `#d1fae5`
- `--primitive-emerald-200`: `#a7f3d0`
- `--primitive-emerald-400`: `#34d399`
- `--primitive-emerald-500`: `#10b981`
- `--primitive-emerald-600`: `#059669`
- `--primitive-emerald-700`: `#047857`
- `--primitive-emerald-800`: `#065f46`
- `--primitive-emerald-900`: `#064e3b`
- `--primitive-emerald-950`: `#022c22`

#### Status Palette (Umpan Balik)
- `--primitive-rose-100`: `#ffe4e6`
- `--primitive-rose-400`: `#fb7185`
- `--primitive-rose-700`: `#be123c`
- `--primitive-rose-950`: `#4c0519`
- `--primitive-amber-100`: `#fef3c7`
- `--primitive-amber-400`: `#fbbf24`
- `--primitive-amber-700`: `#b45309`
- `--primitive-amber-950`: `#451a03`
- `--primitive-sky-500`: `#0ea5e9` (status Gemini jeda atau cooldown)

---

### Lapisan 2: Semantic Tokens (Pemetaan Makna & Tema)

| Token Semantik | Light Theme | Dark Theme (Tema Gelap) | Rationale & Fungsi |
|---|---|---|---|
| `--color-canvas-bg` | `#fafaf9` | `#0c0a09` | Latar belakang seluruh halaman aplikasi |
| `--color-surface-card` | `#ffffff` | `#1c1917` | Kartu konten utama dan kontainer formulir |
| `--color-surface-subtle` | `#f5f5f4` | `#161412` | Latar belakang kontainer dalam, input sekunder |
| `--color-surface-elevated` | `#ffffff` | `#24201e` | Dialog, popover, dropdown pilihan |
| `--color-border-subtle` | `#e7e5e4` | `#292524` | Garis pembatas ringan antar elemen |
| `--color-border-default` | `#d6d3d1` | `#3d3835` | Garis bingkai input, kartu, dan pembatas |
| `--color-border-focus` | `#1c1917` | `#e7e5e4` | Cincin fokus keyboard dan outline aktif |
| `--color-text-primary` | `#1c1917` | `#f5f5f4` | Teks judul utama, isi tebal, kontras tinggi |
| `--color-text-secondary` | `#57534e` | `#a8a29e` | Teks paragraf, label formulir, keterangan |
| `--color-text-tertiary` | `#78716c` | `#78716c` | Placeholder, metadata, tanggal |
| `--color-accent-primary` | `#1c1917` | `#f5f5f4` | Tombol aksi utama kontras tinggi |
| `--color-accent-primary-fg` | `#ffffff` | `#1c1917` | Teks di atas tombol aksi utama |
| `--color-emerald-bg` | `#ecfdf5` | `#022c22` | Latar kartu modul UT dan naskah terverifikasi |
| `--color-emerald-border` | `#a7f3d0` | `#065f46` | Garis kartu modul UT dan naskah terverifikasi |
| `--color-emerald-text` | `#064e3b` | `#34d399` | Teks dan ikon kartu modul UT terverifikasi |
| `--color-danger-bg` | `#ffe4e6` | `#2d0b13` | Latar kotak galat dan status error |
| `--color-danger-border` | `#fda4af` | `#4c0519` | Bingkai kotak galat |
| `--color-danger-text` | `#be123c` | `#fb7185` | Teks pesan galat |

---

### Lapisan 3: Component Tokens (Spesifik Komponen)

```css
/* Card Container */
--comp-card-bg: var(--color-surface-card);
--comp-card-border: var(--color-border-default);
--comp-card-shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.05);

/* Form Input & Select */
--comp-input-bg: var(--color-surface-card);
--comp-input-border: var(--color-border-default);
--comp-input-text: var(--color-text-primary);
--comp-input-placeholder: var(--color-text-tertiary);
--comp-input-focus: var(--color-border-focus);

/* Primary Button */
--comp-btn-primary-bg: var(--color-accent-primary);
--comp-btn-primary-fg: var(--color-accent-primary-fg);
--comp-btn-primary-hover: var(--primitive-stone-800); /* Dark: #e7e5e4 */

/* Secondary Button */
--comp-btn-secondary-bg: var(--color-surface-subtle);
--comp-btn-secondary-border: var(--color-border-default);
--comp-btn-secondary-text: var(--color-text-primary);

/* Step Tab Active */
--comp-step-active-border: var(--color-accent-primary);
--comp-step-active-bg: var(--color-surface-card);
--comp-step-active-text: var(--color-text-primary);

/* Step Tab Completed */
--comp-step-done-border: var(--primitive-emerald-500);
--comp-step-done-bg: var(--color-emerald-bg);
--comp-step-done-text: var(--color-emerald-text);
```

---

## 3. Skala Spasi, Radius, dan Elevasi
- **Radius:**
  - `rounded-lg`: 8px (kontrol kecil, tombol opsi)
  - `rounded-xl`: 12px (input teks, textarea, dropdown, kartu tombol)
  - `rounded-2xl`: 16px (kontainer utama tiap langkah, modal hasil)
- **Spasi:** Skala 4px teratur (p-3, p-4, p-5, p-6, p-8).
- **Aksesibilitas Kontras:** Memenuhi standar rasio kontras WCAG 2.1 minimal 4.5 banding 1 untuk teks normal dan 3 banding 1 untuk teks tebal.
