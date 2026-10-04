import os
import pytest
from playwright.sync_api import sync_playwright

BASE_URL = "http://127.0.0.1:8000"


def test_browser_ui_end_to_end():
    """
    Automated browser test with Playwright using Google Chrome engine.
    Tests the complete end-to-end flow from Step 1 (Question & Identity)
    through Step 2 (Curating Academic Reading Materials)
    to Step 3 (Generated Answer and APA 7th References).
    """
    with sync_playwright() as p:
        # Gunakan browser Google Chrome asli dengan mode headless untuk test otomatis
        try:
            browser = p.chromium.launch(channel="chrome", headless=True)
        except Exception:
            browser = p.chromium.launch(headless=True)

        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()

        # 1. Buka halaman utama
        page.goto(BASE_URL, wait_until="networkidle")
        assert "Asisten Tugas Citra" in page.title()

        # 2. Tunggu status AI ready
        page.wait_for_selector("#api-status-badge", timeout=10000)

        # 3. Tahap 1: Isi soal dan identitas mahasiswa
        topic = (
            "1. Jelaskan konsep dasar manajemen rantai pasok dan perannya dalam efisiensi operasional organisasi.\n"
            "2. Berikan contoh strategi mitigasi risiko disrupsi pasokan pada industri manufaktur."
        )
        page.locator("#input-topic").fill(topic)

        page.locator("#details-identity summary").click()
        page.wait_for_timeout(200)
        page.locator("#input-student-name").fill("Galang Pratama")
        page.locator("#input-student-id").fill("042918231")
        page.locator("#input-course-name").fill("Manajemen Operasi")

        # Pilih Jalur B: Bahan Dosen atau Modul
        page.locator('label.mode-card:has(input[value="bahan"])').click()
        page.wait_for_timeout(300)

        # Klik tombol lanjut ke Tahap 2
        page.locator("#btn-primary-action").click()

        # 4. Tahap 2: Input dan simpan bahan bacaan modul
        page.wait_for_selector("#step-2:not(.hidden)", timeout=10000)
        page.locator("#input-material-title").fill("Manajemen Rantai Pasok (EKMA4371)")
        page.locator("#input-material-author").fill("Universitas Terbuka")
        page.locator("#input-material-year").fill("2021")
        page.locator("#input-material-publisher").fill("Penerbit Universitas Terbuka")
        page.locator("#input-material-page").fill("Modul 3, hlm. 15-32")
        page.locator("#input-material-text").fill(
            "Manajemen rantai pasok mencakup integrasi pengadaan bahan baku, proses produksi, hingga distribusi barang akhir ke konsumen. "
            "Koordinasi terpadu antar pemangku kepentingan mengurangi ketidakpastian permintaan (bullwhip effect), menekan biaya persediaan, "
            "dan menjaga kontinuitas operasional manufaktur secara berkelanjutan."
        )
        page.locator("#btn-save-material").click()
        page.wait_for_timeout(800)

        # Klik tombol Tulis naskah sekarang
        page.locator("#btn-generate").click()

        # 5. Tahap 3: Verifikasi hasil jawaban di browser
        page.wait_for_selector("#step-3:not(.hidden)", timeout=10000)
        page.wait_for_selector("#result-container:not(.hidden)", timeout=120000)
        page.wait_for_selector("#preview-content .paper-heading", timeout=10000)

        # Periksa judul dan bagian naskah
        result_title = page.locator("#result-title").text_content().strip()
        assert len(result_title) > 0

        paragraphs = [p.strip() for p in page.locator("#preview-content p").all_text_contents() if p.strip()]
        assert len(paragraphs) >= 2

        # Periksa bagian Daftar Pustaka standar APA 7th
        headings = [h.strip() for h in page.locator("#preview-content h3.paper-heading, #preview-content h2, #preview-content h3").all_text_contents() if h.strip()]
        assert any("pustaka" in h.lower() or "reference" in h.lower() for h in headings)

        ref_items = [r.strip() for r in page.locator("#preview-content ol li, #preview-content ul li").all_text_contents() if r.strip()]
        assert len(ref_items) >= 1
        ref_text = ref_items[0]
        assert "Universitas Terbuka" in ref_text
        assert "2021" in ref_text
        assert "Penerbit Universitas Terbuka" in ref_text

        print("\n" + "=" * 60)
        print("HASIL AUTOMATED BROWSER TEST (PLAYWRIGHT CHROME):")
        print("=" * 60)
        print(f"Judul Naskah: {result_title}")
        print(f"Heading Referensi: {[h for h in headings if 'pustaka' in h.lower() or 'reference' in h.lower()][0]}")
        print(f"Isi Referensi: {ref_text}")
        print("=" * 60)

        browser.close()
