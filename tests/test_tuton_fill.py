from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

FILL_SRC = (Path(__file__).resolve().parents[1] / "desktop" / "tuton-fill.js").read_text(encoding="utf-8")

# Sama seperti main.js: fungsinya dijalankan di halaman sebagai teks, lepas dari modul aslinya
LOAD_FILL = """(src) => {
  const module = { exports: {} };
  new Function("module", src)(module);
  window.__tuton = { fillAnswer: new Function("return " + module.exports.fillAnswer.toString())() };
}"""

PAGE = """<!doctype html><html><body><div id="region-main">%s</div></body></html>"""
TINYMCE = """<textarea id="id_message" style="display:none"></textarea>
<iframe id="id_message_ifr" srcdoc="<body id='tinymce' contenteditable='true'>%s</body>"></iframe>"""
ATTO = """<div id="id_onlinetexteditable" class="editor_atto_content" contenteditable="true"></div>
<textarea id="id_onlinetext" hidden></textarea>"""
PAYLOAD = {"html": "<p>Paragraf satu.</p><p><strong>Daftar Pustaka</strong></p>", "text": "Paragraf satu.\nDaftar Pustaka", "force": False}


@pytest.fixture(scope="module")
def page():
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as err:
            pytest.skip(f"Chromium Playwright tidak tersedia: {err}")
        yield browser.new_page()
        browser.close()


def load(page, body):
    page.set_content(PAGE % body)
    page.wait_for_load_state("load")
    page.evaluate(LOAD_FILL, FILL_SRC)


def fill(page, **overrides):
    return page.evaluate("(p) => window.__tuton.fillAnswer(p)", {**PAYLOAD, **overrides})


def test_fill_tinymce_iframe(page):
    load(page, TINYMCE % "")
    assert fill(page) == {"ok": True}
    assert page.frame_locator("#id_message_ifr").locator("strong").inner_text() == "Daftar Pustaka"
    assert page.eval_on_selector("#id_message", "t => t.value") == PAYLOAD["html"]


def test_filled_editor_needs_confirm_then_force(page):
    load(page, TINYMCE % "jawaban lama")
    assert fill(page) == {"ok": False, "needsConfirm": True}
    assert fill(page, force=True) == {"ok": True}
    assert "jawaban lama" not in page.frame_locator("#id_message_ifr").locator("body").inner_text()


def test_fill_atto_and_plain_textarea(page):
    load(page, ATTO)
    assert fill(page) == {"ok": True}
    assert page.eval_on_selector("#id_onlinetext", "t => t.value") == PAYLOAD["html"]

    load(page, '<textarea name="post"></textarea>')
    assert fill(page) == {"ok": True}
    assert page.eval_on_selector("textarea", "t => t.value") == PAYLOAD["text"]


def test_no_editor_reports_message(page):
    load(page, "<p>Halaman soal tanpa kolom balasan.</p>")
    result = fill(page)
    assert result["ok"] is False and "Kolom jawaban tidak ditemukan" in result["message"]


# TinyMCE tiruan yang mencatat panggilan API, supaya terlihat isi lewat API editor dan kursor ditaruh di editor
FAKE_TINY = """<div id="tiny-box">editor</div><script>
  window.calls = [];
  const ed = {
    getContainer: () => document.getElementById("tiny-box"),
    getContent: () => window.existing || "",
    setContent: (h) => calls.push("setContent:" + h),
    undoManager: { add: () => calls.push("undo") },
    setDirty: (v) => calls.push("dirty:" + v),
    save: () => calls.push("save"),
    dispatch: (name) => calls.push("event:" + name),
    focus: () => calls.push("focus"),
    getBody: () => document.body,
    selection: { select: () => calls.push("select"), collapse: (start) => calls.push("collapse:" + start) },
  };
  window.tinymce = { get: () => [ed] };
</script>"""


def test_fill_uses_tinymce_api_and_puts_caret_in_editor(page):
    load(page, FAKE_TINY)
    assert fill(page) == {"ok": True}
    assert page.evaluate("calls") == [
        "setContent:" + PAYLOAD["html"], "undo", "save", "dirty:true", "event:change", "focus", "select", "collapse:false",
    ]
    page.evaluate("window.existing = 'jawaban lama'")
    assert fill(page) == {"ok": False, "needsConfirm": True}
