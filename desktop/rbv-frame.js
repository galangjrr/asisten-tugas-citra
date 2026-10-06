// Mencari bingkai lembar buku yang sedang tampil di pembaca RBV, supaya F9 hanya memotret isi buku tanpa menu dan bilah pembaca.
// Fungsi ini diubah jadi teks lalu dijalankan di halaman pembaca lewat executeJavaScript, jadi tidak boleh memakai variabel luar.
// Hasil null berarti bingkai tidak ditemukan dan jendela dipotret utuh seperti biasa.
function findBookFrame() {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  // RBV memakai FlowPaper. Pembaca PDF lain biasanya menaruh tiap lembar di .page, kanvas, atau gambar besar.
  const PAGE = ".flowpaper_page, .pdfViewer .page";
  const pageOf = (node) => (node.closest && node.closest(PAGE)) || (node.matches && node.matches("canvas, img") ? node : null);
  const boxes = [];
  document.querySelectorAll(`${PAGE}, canvas, img`).forEach((el) => {
    const r = el.getBoundingClientRect();
    const left = Math.max(0, r.left);
    const top = Math.max(0, r.top);
    const right = Math.min(vw, r.right);
    const bottom = Math.min(vh, r.bottom);
    // Lembar kecil seperti ikon dan thumbnail diabaikan
    if ((right - left) * (bottom - top) < vw * vh * 0.1) return;
    // Lembar yang bertumpuk di belakang lembar lain tidak ikut. Semua lapisan di titik tengah diperiksa, karena saat kursor
    // di atas buku FlowPaper menaruh lapisan efek balik halaman di atas lembar.
    const stack = document.elementsFromPoint((left + right) / 2, (top + bottom) / 2);
    const front = stack.map(pageOf).find(Boolean);
    if (!front || !(front === el || el.contains(front) || front.contains(el))) return;
    boxes.push({ left, top, right, bottom });
  });
  if (!boxes.length) return null;
  const pad = 6;
  const left = Math.max(0, Math.min(...boxes.map((b) => b.left)) - pad);
  const top = Math.max(0, Math.min(...boxes.map((b) => b.top)) - pad);
  const right = Math.min(vw, Math.max(...boxes.map((b) => b.right)) + pad);
  const bottom = Math.min(vh, Math.max(...boxes.map((b) => b.bottom)) + pad);
  return { x: Math.round(left), y: Math.round(top), width: Math.round(right - left), height: Math.round(bottom - top) };
}

module.exports = { findBookFrame };
