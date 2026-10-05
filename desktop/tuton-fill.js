// Mengisi kolom jawaban Moodle di halaman Tuton. Fungsi ini diubah jadi teks lalu dijalankan di dunia utama halaman
// lewat executeJavaScript, jadi isinya harus berdiri sendiri tanpa memakai apa pun dari luar fungsi.
// Hanya mengisi kolom jawaban. Tombol Kirim atau Simpan perubahan di Tuton tidak pernah disentuh.
function fillAnswer({ html, text, force }) {
  const scope = document.querySelector("#region-main") || document.body;
  const visible = (node) => node.getClientRects().length > 0;
  const notFound = {
    ok: false,
    message: "Kolom jawaban tidak ditemukan. Klik Balas di diskusi atau Tambah pengumpulan di tugas sampai kolom tulisnya muncul, lalu coba lagi.",
  };

  // TinyMCE di Moodle 4. Isi lewat API editornya supaya undo, tanda berubah, dan simpan otomatis Moodle ikut tahu,
  // lalu kursor ditaruh di akhir naskah supaya ketikan langsung masuk ke editor.
  const editors = window.tinymce && typeof window.tinymce.get === "function" ? window.tinymce.get() || [] : [];
  const tiny = Array.from(editors).find((ed) => {
    const box = ed.getContainer && ed.getContainer();
    return box && scope.contains(box) && visible(box);
  });
  if (tiny) {
    if (tiny.getContent({ format: "text" }).trim() && !force) return { ok: false, needsConfirm: true };
    tiny.setContent(html);
    tiny.undoManager.add();
    // save menyalin isi ke textarea asli sekaligus mereset tanda berubah, jadi tandanya dipasang setelahnya
    tiny.save();
    tiny.setDirty(true);
    (tiny.dispatch || tiny.fire).call(tiny, "change");
    tiny.getContainer().scrollIntoView({ block: "center" });
    tiny.focus();
    tiny.selection.select(tiny.getBody(), true);
    tiny.selection.collapse(false);
    return { ok: true };
  }

  // Cadangan tanpa API editor: iframe TinyMCE, div contenteditable Atto, atau textarea polos seperti balasan cepat forum
  let node = null;
  let source = null;
  let isHtml = true;
  const frame = Array.from(scope.querySelectorAll("iframe[id$='_ifr']")).find(visible);
  const atto = Array.from(scope.querySelectorAll(".editor_atto_content[contenteditable='true']")).find(visible);
  const area = Array.from(scope.querySelectorAll("textarea")).find((t) => visible(t) && !t.readOnly && !t.disabled);
  if (frame && frame.contentDocument && frame.contentDocument.body) {
    node = frame.contentDocument.body;
    source = document.getElementById(frame.id.slice(0, -4));
  } else if (atto) {
    node = atto;
    source = document.getElementById(atto.id.replace(/editable$/, ""));
  } else if (area) {
    node = area;
    isHtml = false;
  } else {
    return notFound;
  }

  const existing = isHtml ? node.textContent : node.value;
  if (existing.trim() && !force) return { ok: false, needsConfirm: true };
  if (isHtml) {
    node.innerHTML = html;
    // Textarea asli ikut diisi supaya isinya tetap ada walau editor belum sempat menyalin sendiri
    if (source) source.value = html;
  } else {
    node.value = text;
  }
  node.dispatchEvent(new Event("input", { bubbles: true }));
  if (source) source.dispatchEvent(new Event("change", { bubbles: true }));
  (frame && node.ownerDocument !== document ? frame : node).scrollIntoView({ block: "center" });
  if (node.ownerDocument !== document) node.ownerDocument.defaultView.focus();
  node.focus();
  return { ok: true };
}

module.exports = { fillAnswer };
