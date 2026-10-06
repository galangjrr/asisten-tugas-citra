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
  const ul = Math.min(...boxes.map((b) => b.left));
  const ut = Math.min(...boxes.map((b) => b.top));
  const ur = Math.max(...boxes.map((b) => b.right));
  const ub = Math.max(...boxes.map((b) => b.bottom));

  // Lembar bisa tertutup menu samping atau bilah pembaca. Titik dicek di lima baris dan lima kolom: titik yang elemen
  // paling atasnya bukan bagian lembar dianggap tertutup, lalu bingkai dipersempit ke area lembar yang benar-benar terlihat.
  // Wadah pembaca dan pembungkus efek balik halaman tidak menutupi apa pun, jadi dilewati: yang berisi lembar buku,
  // atau yang kosong tanpa teks dan tanpa latar. Yang dianggap menutup hanya elemen yang tampak, misalnya menu samping.
  const passThrough = (node) => {
    if (node.querySelector(PAGE)) return true;
    if (node.childElementCount || node.textContent.trim()) return false;
    const st = getComputedStyle(node);
    return st.backgroundImage === "none" && (st.backgroundColor === "transparent" || /rgba\(.*,\s*0\)$/.test(st.backgroundColor));
  };
  const isBook = (x, y) => {
    for (const node of document.elementsFromPoint(x, y)) {
      if (pageOf(node)) return true;
      if (!passThrough(node)) return false;
    }
    return false;
  };
  const step = 10;
  const fractions = [0.15, 0.35, 0.5, 0.65, 0.85];
  let left = Infinity;
  let right = -Infinity;
  let top = Infinity;
  let bottom = -Infinity;
  fractions.forEach((f) => {
    const y = ut + (ub - ut) * f;
    for (let x = ul + 1; x < ur; x += step) {
      if (isBook(x, y)) {
        left = Math.min(left, x);
        right = Math.max(right, x);
      }
    }
    const x = ul + (ur - ul) * f;
    for (let yy = ut + 1; yy < ub; yy += step) {
      if (isBook(x, yy)) {
        top = Math.min(top, yy);
        bottom = Math.max(bottom, yy);
      }
    }
  });
  if (!isFinite(left) || !isFinite(top)) return null;
  // Sisa langkah sampel ditambahkan supaya tepi lembar tidak terpotong
  right = Math.min(ur, right + step);
  bottom = Math.min(ub, bottom + step);
  // Bagian kiri atau kanan lembar yang tertutup lebih dari 3 persen ditandai, supaya pengguna diminta menutup menu pembaca
  const clipped = right - left < (ur - ul) * 0.97;
  // Area terlihat kurang dari separuh biasanya karena efek hover atau animasi balik halaman sesaat, bukan menu.
  // Potongan sekecil itu merusak OCR, jadi bentangan utuh yang dipakai dan pengguna tetap diberi tahu.
  if ((right - left) * (bottom - top) < (ur - ul) * (ub - ut) * 0.5) {
    left = ul;
    right = ur;
    top = ut;
    bottom = ub;
  }

  const pad = 6;
  left = Math.max(0, left - pad);
  top = Math.max(0, top - pad);
  right = Math.min(vw, right + pad);
  bottom = Math.min(vh, bottom + pad);
  return { x: Math.round(left), y: Math.round(top), width: Math.round(right - left), height: Math.round(bottom - top), clipped };
}

module.exports = { findBookFrame };
