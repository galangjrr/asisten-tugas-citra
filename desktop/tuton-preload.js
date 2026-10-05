// Preload jendela Tuton. Berjalan di dunia terisolasi, jadi skrip halaman Tuton tidak bisa memanggil ipcRenderer.
// Tugasnya cuma satu: saat tombol Pakai soal ini diklik, baca halaman yang sedang terbuka lalu kirim ke jendela Asisten.
const { ipcRenderer } = require("electron");

// Gambar lebih kecil dari ini biasanya ikon atau emotikon, bukan bagian soal
const MIN_IMAGE_SIDE = 40;
const MIN_IMAGE_BYTES = 2 * 1024;
const MAX_IMAGES = 12;
const MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024;

// Urutan pencarian isi soal. Forum diskusi Moodle 4 dan 3, lalu deskripsi tugas, lalu seluruh isi halaman.
// Tugas di tema Tuton UT (mb2iq) ada di .activity-header .generalbox, terpisah dari tanggal buka dan tenggat.
// ponytail: forum diskusi di tema Tuton belum dicek di halaman asli, selector forum masih dari Moodle bawaan.
const QUESTION_SELECTORS = [
  ".forumpost .post-content-container",
  ".forumpost .posting",
  ".activity-header .generalbox",
  ".activity-description",
  "#intro",
  "#region-main",
];
const TITLE_SELECTORS = [
  "[data-region-content='forum-post-core-subject']",
  ".discussionname",
  "h2.activity-name",
  ".activity-header h2",
  "#region-main h2",
  ".page-header-headings h1",
];
const SKIP_SELECTOR = "style, noscript, button, .accesshide, .sr-only, .MathJax, .MathJax_Preview, .MathJax_Display, [hidden]";
const BLOCK_TAGS = new Set(["P", "DIV", "LI", "H1", "H2", "H3", "H4", "H5", "H6", "TR", "BLOCKQUOTE", "PRE", "TABLE", "UL", "OL", "SECTION", "ARTICLE", "FIGURE"]);

const clean = (text) => (text || "").replace(/\s+/g, " ").trim();
const firstText = (selectors, scope = document) => {
  for (const sel of selectors) {
    const node = scope.querySelector(sel);
    if (node && clean(node.textContent)) return clean(node.textContent);
  }
  return "";
};

function findQuestionRoot() {
  for (const sel of QUESTION_SELECTORS) {
    const node = document.querySelector(sel);
    if (node && clean(node.textContent).length >= 3) return node;
  }
  return null;
}

// Mengubah isi soal jadi teks berurutan. Gambar diganti penanda [[GAMBAR_n]] sesuai urutan kemunculannya,
// sama seperti pembaca berkas docx, supaya backend bisa mencocokkan deskripsi gambar ke posisinya.
function toText(root, images) {
  const out = [];
  const walk = (node) => {
    if (node.nodeType === Node.TEXT_NODE) {
      out.push(node.nodeValue.replace(/\s+/g, " "));
      return;
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return;
    const tag = node.tagName;
    // Rumus MathJax 2 menyimpan TeX aslinya di script math/tex, tampilan renderannya dilewati
    if (tag === "SCRIPT") {
      if ((node.type || "").startsWith("math/tex")) out.push(` \\(${node.textContent.trim()}\\) `);
      return;
    }
    if (node.matches(SKIP_SELECTOR)) return;
    // MathJax 3 tidak menyimpan TeX, jadi pakai versi MathML untuk pembaca layar
    if (tag === "MJX-CONTAINER") {
      const mml = node.querySelector("mjx-assistive-mml");
      out.push(` ${clean((mml || node).textContent)} `);
      return;
    }
    if (tag === "IMG") {
      const small = node.naturalWidth < MIN_IMAGE_SIDE && node.naturalHeight < MIN_IMAGE_SIDE;
      if (small || node.closest(".userpicture, .icon") || images.length >= MAX_IMAGES) return;
      out.push(` [[GAMBAR_${images.length}]] `);
      images.push(node.currentSrc || node.src);
      return;
    }
    if (tag === "BR") {
      out.push("\n");
      return;
    }
    const block = BLOCK_TAGS.has(tag);
    if (block) out.push("\n");
    if (tag === "LI") {
      const list = node.parentElement;
      if (list && list.tagName === "OL") {
        const start = Number(list.getAttribute("start") || 1);
        out.push(`${start + Array.prototype.indexOf.call(list.children, node)}. `);
      } else {
        out.push("- ");
      }
    }
    if (tag === "TD" || tag === "TH") out.push(" | ");
    node.childNodes.forEach(walk);
    if (block) out.push("\n");
  };
  walk(root);
  return out.join("").replace(/[ \t]+/g, " ").replace(/ ([.,;:?!])/g, "$1").replace(/ *\n */g, "\n").replace(/^(\d+\.|-)\n+/gm, "$1 ").replace(/\n{3,}/g, "\n\n").trim();
}

function blobToDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

// Gambar diambil memakai cookie login Tuton yang sama. Gambar yang gagal diambil dibuang penandanya,
// lalu nomor penanda disusun ulang supaya tetap cocok dengan urutan daftar gambar yang dikirim.
async function fetchImages(text, sources) {
  const images = [];
  const remap = {};
  for (let i = 0; i < sources.length; i += 1) {
    try {
      const res = await fetch(sources[i], { credentials: "include" });
      const blob = await res.blob();
      if (!res.ok || !blob.type.startsWith("image/") || blob.size < MIN_IMAGE_BYTES) continue;
      remap[i] = images.length;
      images.push({ data_base64: await blobToDataUrl(blob), mime: blob.type });
    } catch (err) {
      /* gambar gagal diambil, penandanya dibuang di bawah */
    }
  }
  const fixed = text.replace(/\[\[GAMBAR_(\d+)\]\]/g, (_m, n) => (n in remap ? `[[GAMBAR_${remap[n]}]]` : ""));
  return { text: fixed, images };
}

// Lembar soal tugas sering berupa lampiran. Lampiran PDF atau Word pertama diambil di belakang layar.
async function fetchAttachment(root) {
  const scope = root.closest(".forumpost, .activity-header, #intro, #region-main") || root;
  const link = Array.from(scope.querySelectorAll("a[href*='pluginfile.php']")).find((a) => {
    const path = decodeURIComponent(new URL(a.href).pathname).toLowerCase();
    return path.endsWith(".pdf") || path.endsWith(".docx");
  });
  if (!link) return null;
  const name = decodeURIComponent(new URL(link.href).pathname.split("/").pop());
  const res = await fetch(link.href, { credentials: "include" });
  if (!res.ok) throw new Error(`Lampiran ${name} gagal diambil, kode ${res.status}.`);
  const blob = await res.blob();
  if (blob.size > MAX_ATTACHMENT_BYTES) throw new Error(`Lampiran ${name} lebih dari 20MB.`);
  return { name, data: await blobToDataUrl(blob) };
}

// Menu akun Tuton menulis nama kapital diikuti NIM, misalnya "CITRA NUR ANNISSA 058215934"
function readStudent() {
  const raw = firstText([".usermenu .usertext", ".usertext"]);
  const match = raw.match(/^(.*?)\s*(\d{8,10})$/);
  const name = (match ? match[1] : raw).toLowerCase().replace(/(^|[\s'-])\p{L}/gu, (c) => c.toUpperCase());
  return { name, nim: match ? match[2] : "" };
}

// Breadcrumb Tuton: teks link berisi kode kelas seperti FSSI4105.4, atribut title berisi nama mata kuliah
function courseInfo() {
  const courseLink = document.querySelector(".breadcrumb a[href*='/course/view.php']");
  const name = (courseLink && clean(courseLink.title)) || firstText([".page-header-headings h1", ".page-context-header h1"]);
  const label = [courseLink && courseLink.textContent, name, document.title].filter(Boolean).join(" ");
  return { name, label: clean(label) };
}

async function capture() {
  const root = findQuestionRoot();
  if (!root) throw new Error("Isi soal tidak ditemukan di halaman ini.");
  const sources = [];
  const rawText = toText(root, sources);
  const [{ text, images }, attachment] = await Promise.all([fetchImages(rawText, sources), fetchAttachment(root)]);
  const course = courseInfo();
  const student = readStudent();
  return {
    url: location.href,
    title: firstText(TITLE_SELECTORS) || clean(document.title),
    courseName: course.name,
    courseLabel: course.label,
    studentName: student.name,
    studentId: student.nim,
    text,
    images,
    attachment,
  };
}

// Tombol mengambang di dalam shadow root supaya gaya Tuton dan gaya tombol tidak saling bocor
function mountButton() {
  if (!location.pathname.includes("/mod/") || document.getElementById("atc-capture-host")) return;
  const host = document.createElement("div");
  host.id = "atc-capture-host";
  const shadow = host.attachShadow({ mode: "closed" });
  shadow.innerHTML = `
    <style>
      .wrap { position: fixed; right: 20px; bottom: 20px; z-index: 2147483647; display: flex; flex-direction: column; align-items: flex-end; gap: 8px; font-family: "Plus Jakarta Sans", "Segoe UI", sans-serif; }
      button { display: inline-flex; align-items: center; gap: 8px; padding: 12px 18px; border: 0; border-radius: 12px; background: #1c1917; color: #fafaf9; font: 600 13px/1 inherit; cursor: pointer; box-shadow: 0 10px 24px -10px rgba(12, 10, 9, 0.6); transition: transform 120ms ease, background-color 120ms ease; }
      button:hover:not(:disabled) { background: #292524; transform: translateY(-2px); }
      button:focus-visible { outline: 2px solid #059669; outline-offset: 2px; }
      button:disabled { opacity: 0.7; cursor: progress; }
      .dot { width: 8px; height: 8px; border-radius: 999px; background: #10b981; }
      .status { max-width: 320px; padding: 8px 12px; border-radius: 10px; background: #fafaf9; color: #44403c; font: 500 12px/1.45 inherit; box-shadow: 0 6px 18px -10px rgba(12, 10, 9, 0.5); }
      .status:empty { display: none; }
      .status.error { background: #fef2f2; color: #991b1b; }
      @media (prefers-reduced-motion: reduce) { button { transition: none; } }
    </style>
    <div class="wrap">
      <div class="status" role="status" aria-live="polite"></div>
      <button type="button"><span class="dot" aria-hidden="true"></span><span class="label">Pakai soal ini di Asisten</span></button>
    </div>`;
  const button = shadow.querySelector("button");
  const label = shadow.querySelector(".label");
  const status = shadow.querySelector(".status");
  const setStatus = (text, isError) => {
    status.textContent = text;
    status.classList.toggle("error", Boolean(isError));
  };

  button.addEventListener("click", async () => {
    button.disabled = true;
    label.textContent = "Membaca halaman";
    setStatus("");
    try {
      const payload = await capture();
      ipcRenderer.send("tuton-capture", payload);
      setStatus(`Terkirim ke Asisten${payload.attachment ? `, lampiran ${payload.attachment.name} ikut dibaca` : ""}.`);
    } catch (err) {
      setStatus(err.message || "Halaman ini belum bisa dibaca.", true);
    } finally {
      button.disabled = false;
      label.textContent = "Pakai soal ini di Asisten";
    }
  });
  document.body.append(host);
}

// Login Tuton lewat akun Microsoft UT. NIM tanpa @ecampus.ut.ac.id dibaca Microsoft sebagai nomor telepon
// lalu login berhenti di layar konfirmasi nomor. Isian login tidak disentuh, cukup diberi petunjuk.
function mountLoginHint() {
  if (location.hostname !== "login.microsoftonline.com" || document.getElementById("atc-login-hint")) return;
  const host = document.createElement("div");
  host.id = "atc-login-hint";
  const shadow = host.attachShadow({ mode: "closed" });
  shadow.innerHTML = `
    <style>
      .hint { position: fixed; top: 16px; left: 50%; transform: translateX(-50%); z-index: 2147483647; width: max-content; max-width: min(520px, calc(100vw - 32px)); padding: 12px 16px; border-radius: 12px; background: #1c1917; color: #fafaf9; font: 500 13px/1.5 "Plus Jakarta Sans", "Segoe UI", sans-serif; box-shadow: 0 10px 24px -10px rgba(12, 10, 9, 0.6); }
      b { color: #6ee7b7; font-weight: 600; }
    </style>
    <div class="hint" role="note">Masuk pakai email kampus <b>NIM@ecampus.ut.ac.id</b>, contohnya 048123456@ecampus.ut.ac.id. Kalau cuma NIM, Microsoft mengira itu nomor telepon.</div>`;
  document.body.append(host);
}

window.addEventListener("DOMContentLoaded", () => {
  mountButton();
  mountLoginHint();
});
