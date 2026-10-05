import pytest
from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)


def test_extract_screenshot_empty_payload():
    response = client.post("/api/extract-screenshot", json={"image_data": ""})
    assert response.status_code == 400


def test_extract_screenshot_invalid_base64():
    response = client.post("/api/extract-screenshot", json={"image_data": "invalid_data"})
    assert response.status_code == 400


def test_ut_course_lookup_expanded_catalog():
    # Test FSSI4206 (KRS code) and FSSI4316 (Bahan ajar code)
    res1 = client.get("/api/ut-course-lookup?query=FSSI4206")
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["found"] is True
    assert "Morpho-Syntax" in data1["course"]["nama"]

    res2 = client.get("/api/ut-course-lookup?query=FSSI4316")
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["found"] is True
    assert "Morpho-Syntax" in data2["course"]["nama"]


def test_smart_crop_book_spread_non_reader_fallback():
    from tools.ocr_vision import smart_crop_book_spread
    # Empty or small input
    assert smart_crop_book_spread(b"") == b""
    assert smart_crop_book_spread(b"123") == b"123"

    # Non-reader image (e.g. solid color) should return original
    import io
    from PIL import Image
    im = Image.new("RGB", (500, 500), color=(200, 200, 200))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    original_bytes = buf.getvalue()
    assert smart_crop_book_spread(original_bytes) == original_bytes


def test_smart_crop_book_spread_crops_dark_frame():
    import io
    from PIL import Image
    from tools.ocr_vision import smart_crop_book_spread

    # Create mock reader image: dark frame around white center page
    # Total 600x600, top 100 dark (y:0..100), bottom 100 dark (y:500..600), left 100 dark (x:0..100), right 100 dark (x:500..600)
    im = Image.new("RGB", (600, 600), color=(20, 20, 30))
    # Draw white center page
    from PIL import ImageDraw
    draw = ImageDraw.Draw(im)
    draw.rectangle([100, 100, 500, 500], fill=(255, 255, 255))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    raw = buf.getvalue()

    cropped_raw = smart_crop_book_spread(raw)
    cropped_im = Image.open(io.BytesIO(cropped_raw))
    # Cropped image must be smaller than 600x600 and within the page area
    assert cropped_im.size[0] < 600
    assert cropped_im.size[1] < 600
    assert cropped_im.size[0] > 200
    assert cropped_im.size[1] > 200



def test_strip_markdown_ocr_output():
    from tools.ocr_vision import strip_markdown
    raw = (
        "```\n## Kegiatan Belajar 1\n\n**Morfologi** adalah *ilmu* tentang __bentuk__ kata.\n\n---\n\n"
        "* poin satu\n+ poin dua\n> kutipan `istilah`\n***\n```"
    )
    assert strip_markdown(raw) == (
        "Kegiatan Belajar 1\n\nMorfologi adalah ilmu tentang bentuk kata.\n\n"
        "- poin satu\n- poin dua\nkutipan istilah"
    )
    # Perkalian, nama berkas, dan tanda hubung biasa tidak boleh rusak
    assert strip_markdown("2*3*4 = 24, file nama_file_baru, 2 * 3 dan - poin") == "2*3*4 = 24, file nama_file_baru, 2 * 3 dan - poin"
