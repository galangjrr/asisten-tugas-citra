/* Asisten Tugas Citra. Tiga lapis terpisah: State aplikasi, Api (HTTP service), dan UI (render DOM).
   Event listener hanya memanggil fungsi alur di bagian bawah, tidak memanggil fetch langsung. */

// =====================================================================
// 1. STATE APLIKASI
// =====================================================================
const STORAGE = {
  theme: "atc-theme",
  tone: "atc-user-tone",
  quoteCitations: "atc-quote-citations",
  name: "atc-student-name",
  nim: "atc-student-id",
  draft: "atc-question-draft",
  // Rubrik dosen dan spesifikasi jawaban ikut disimpan, supaya batas kata dosen tidak hilang saat aplikasi dibuka ulang
  draftSetup: "atc-question-setup",
  mode: "atc-mode"
};

const MODES = {
  forum: {
    action: "Tulis Jawaban Diskusi Sekarang",
    hint: "Langsung ke Tahap 3 tanpa pencarian jurnal. Jawaban siap ditempel ke forum e-learning."
  },
  bahan: {
    action: "Lanjut: Masukkan Bahan Bacaan",
    hint: "Berikutnya Tahap 2. Unggah cerpen, bab buku, atau modul dari dosen untuk dibedah."
  },
  jurnal: {
    action: "Lanjut: Cari Jurnal Ilmiah",
    hint: "Berikutnya Tahap 2. Artikel terbuka dicari di OpenAlex memakai kata kunci dari soal."
  }
};

const DIRECT_ANSWER_TYPES = ["terjemahan", "jawaban_singkat"];
// Jenis jawaban ini sudah menentukan susunan naskah, jadi pilihan format disembunyikan
const FORMAT_DECIDED_TYPES = ["esai", "makalah", "terjemahan", "jawaban_singkat", "jawaban_bernomor"];
const LENGTH_WORDS = { ringkas: 400, sedang: 950, panjang: 1800 };

const State = {
  step: 1,
  maxStep: 1,
  mode: "jurnal",
  questionFileName: "",
  // Batas per soal yang berbeda tiap nomor dari lembar soal, misal soal 1 maksimal 200 dan soal 2 maksimal 300
  detectedItemLimits: null,
  // Format bagian wajib dari dosen tidak punya kolom sendiri, jadi dibawa apa adanya ke permintaan generate
  detectedSections: null,
  specSource: null,
  papers: [],
  selectedPaperIds: new Set(),
  lastQuery: "",
  materials: [],
  savedModules: [],
  generating: false,
  taskId: null,
  doc: null,
  docBusy: false,
  // Versi lama tiap bagian sebelum diedit atau ditulis ulang, supaya bisa dikembalikan. Kunci: nomor bagian.
  sectionHistory: {}
};

const storage = {
  get(key) {
    try { return localStorage.getItem(key) || ""; } catch (err) { return ""; }
  },
  set(key, value) {
    try { localStorage.setItem(key, value); } catch (err) { /* profil webview read-only, abaikan */ }
  },
  remove(key) {
    try { localStorage.removeItem(key); } catch (err) { /* abaikan */ }
  }
};

// =====================================================================
// 2. API (HTTP SERVICE)
// =====================================================================
class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
  get isRateLimited() {
    return this.status === 429 || this.status === 503 || /limit|sibuk|jeda|quota|kuota/i.test(this.message);
  }
}

const Api = {
  async request(url, options = {}) {
    let res;
    try {
      res = await fetch(url, options);
    } catch (err) {
      throw new ApiError("Server lokal tidak merespons. Tutup lalu buka lagi aplikasinya.", 0);
    }
    let data = null;
    try { data = await res.json(); } catch (err) { data = null; }
    if (!res.ok) {
      const detail = data && data.detail;
      const message = typeof detail === "string" ? detail
        : Array.isArray(detail) ? "Ada isian yang belum valid. Periksa lagi lalu coba ulang."
        : `Server membalas kode ${res.status}.`;
      throw new ApiError(message, res.status);
    }
    return data;
  },
  postJson(url, body) {
    return this.request(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  },
  upload(url, file) {
    const form = new FormData();
    form.append("file", file);
    return this.request(url, { method: "POST", body: form });
  },
  health: () => Api.request("/api/health"),
  uploadQuestion: (file) => Api.upload("/api/upload-question-file", file),
  parseReadingDoc: (file) => Api.upload("/api/parse-reading-doc", file),
  saveMaterial: (payload) => Api.postJson("/api/manual-module", payload),
  lookupPublication: (title, author) => Api.postJson("/api/lookup-publication", { title, author: author || null }),
  search: (query, limit) => Api.postJson("/api/search", { query, limit }),
  generate: (payload) => Api.postJson("/api/generate", payload),
  utLookup: (query) => Api.request(`/api/ut-course-lookup?query=${encodeURIComponent(query)}`),
  extractScreenshot: (dataUrl) => Api.postJson("/api/extract-screenshot", { image_data: dataUrl }),
  updateTask: (id, doc) => Api.request(`/api/tasks/${id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(doc) }),
  rewriteSection: (id, index, instruction) => Api.postJson(`/api/tasks/${id}/sections/${index}/rewrite`, { instruction }),
  getSavedModules: () => Api.request("/api/saved-modules"),
  loadSavedModule: (moduleId) => Api.postJson("/api/saved-modules/load", { module_id: moduleId }),
  saveSavedModule: (payload) => Api.postJson("/api/saved-modules/save", payload)
};

// =====================================================================
// 3. UI (RENDER DOM)
// =====================================================================
const $ = (id) => document.getElementById(id);

const dom = {
  statusBadge: $("api-status-badge"),
  stepper: $("stepper"),
  alert: $("global-alert"),
  steps: [$("step-1"), $("step-2"), $("step-3")],
  formTask: $("form-task"),
  topic: $("input-topic"),
  draftStatus: $("draft-status"),
  topicMeta: $("question-type-meta"),
  tabType: $("tab-type"),
  tabUpload: $("tab-upload"),
  panelType: $("panel-type"),
  panelUpload: $("panel-upload"),
  questionFile: $("upload-question-file"),
  questionDropzone: $("question-dropzone"),
  questionUploading: $("question-uploading"),
  questionUploadingText: $("question-uploading-text"),
  questionPreview: $("question-preview"),
  questionPreviewBody: $("question-preview-body"),
  questionPreviewMeta: $("question-preview-meta"),
  questionFileName: $("question-file-name"),
  questionCharBadge: $("question-char-badge"),
  toneSummary: $("tone-summary"),
  detailsTone: $("details-tone"),
  detailsSpec: $("details-spec"),
  specSummary: $("spec-summary"),
  specNote: $("answer-spec-note"),
  specAnswerType: $("spec-answer-type"),
  specQuestionCount: $("spec-question-count"),
  specLanguage: $("spec-language"),
  specWordLimit: $("spec-word-limit"),
  specWordScope: $("spec-word-scope"),
  specWordSummary: $("spec-word-summary"),
  formatWrapper: $("format-wrapper"),
  lengthWrapper: $("length-target-wrapper"),
  selectLength: $("select-length"),
  customWordsWrapper: $("custom-words-wrapper"),
  customWords: $("input-custom-words"),
  selectDepth: $("select-depth"),
  quoteCitations: $("input-quote-citations"),
  instructions: $("input-instructions"),
  identitySummary: $("identity-summary"),
  studentName: $("input-student-name"),
  studentId: $("input-student-id"),
  courseName: $("input-course-name"),
  primaryLabel: $("primary-action-label"),
  primaryHint: $("primary-action-hint"),
  step2Title: $("step-2-title"),
  step2Lede: $("step-2-lede"),
  panelBahan: $("panel-bahan"),
  panelJurnal: $("panel-jurnal"),
  materialFile: $("upload-material-file"),
  materialDropzone: $("material-dropzone"),
  materialReading: $("material-reading"),
  materialReadingText: $("material-reading-text"),
  materialTitle: $("input-material-title"),
  materialUtSpinner: $("material-ut-spinner"),
  materialUtResult: $("material-ut-result"),
  materialAuthor: $("input-material-author"),
  materialYear: $("input-material-year"),
  materialPublisher: $("input-material-publisher"),
  materialPage: $("input-material-page"),
  btnLookupPublication: $("btn-lookup-publication"),
  publicationResult: $("publication-result"),
  materialText: $("input-material-text"),
  materialTextMeta: $("material-text-meta"),
  materialScreenshot: $("upload-material-screenshot"),
  materialOcrStatus: $("material-ocr-status"),
  materialChunks: $("material-chunks"),
  materialChunkCount: $("material-chunk-count"),
  materialList: $("material-list"),
  btnSaveMaterial: $("btn-save-material"),
  btnSaveToLibrary: $("btn-save-to-library"),
  panelSavedLibrary: $("panel-saved-library"),
  savedLibraryCount: $("saved-library-count"),
  savedModulesContainer: $("saved-modules-container"),
  btnRefreshSavedLibrary: $("btn-refresh-saved-library"),
  refineForm: $("form-refine"),
  refineQuery: $("input-refine-query"),
  btnRefine: $("btn-refine-search"),
  searchInfo: $("search-backend-info"),
  btnToggleManual: $("btn-toggle-manual"),
  manualForm: $("manual-paper-wrapper"),
  manualDoi: $("input-manual-doi"),
  btnAddManual: $("btn-add-manual-paper"),
  papersLoading: $("papers-loading"),
  papersList: $("papers-list"),
  selectedCount: $("selected-count-label"),
  selectedHint: $("selected-hint"),
  btnGenerate: $("btn-generate"),
  generating: $("generating-indicator"),
  genStepTitle: $("gen-step-title"),
  pipeline: $("pipeline"),
  result: $("result-container"),
  resultTitle: $("result-title"),
  resultStats: $("result-stats"),
  evidence: $("evidence-container"),
  evidenceList: $("evidence-list"),
  evidenceCount: $("evidence-count-badge"),
  paper: $("preview-content"),
  btnRegenerate: $("btn-regenerate-all"),
  confirmDialog: $("dialog-confirm"),
  confirmTitle: $("confirm-title"),
  confirmMessage: $("confirm-message"),
  confirmOk: $("btn-confirm-ok"),
  toastRegion: $("toast-region")
};

const ICON = {
  check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>',
  alert: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="M12 8v4"/><path d="M12 16h.01"/></svg>',
  success: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/></svg>',
  search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M4.27 21.7A2 2 0 0 0 6 22h12a2 2 0 0 0 2-2V7l-5-5H6a2 2 0 0 0-2 2v3.3"/><circle cx="5" cy="14" r="3"/><path d="m9 18-1.5-1.5"/></svg>',
  book: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 7v14"/><path d="M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z"/></svg>',
  trash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>'
};

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text == null ? "" : String(text);
  return div.innerHTML;
}

function formatNumber(n) {
  return Number(n).toLocaleString("id-ID");
}

function countWords(text) {
  const words = (text || "").replace(/\[Gambar:[\s\S]*?\]/g, " ").match(/\S+/g);
  return words ? words.length : 0;
}

function readInt(input) {
  const n = parseInt(input.value, 10);
  return Number.isFinite(n) ? n : null;
}

function radioValue(name) {
  const checked = document.querySelector(`input[name="${name}"]:checked`);
  return checked ? checked.value : "";
}

function setRadio(name, value) {
  const input = document.querySelector(`input[name="${name}"][value="${value}"]`);
  if (input) input.checked = true;
  return Boolean(input);
}

function setBusy(button, busy, label) {
  if (!button.dataset.label) button.dataset.label = button.innerHTML;
  button.disabled = busy;
  button.classList.toggle("is-loading", busy);
  button.innerHTML = busy ? `<span class="spinner" aria-hidden="true"></span>${escapeHtml(label)}` : button.dataset.label;
}

function formatAuthorsAPA(authors) {
  if (!authors || !authors.length) return "Anonim";
  const institutional = ["universitas", "kementerian", "badan", "lembaga", "organisasi", "bureau", "department", "ministry", "organization", "institute", "university", "press", "who", "unesco", "anonim"];
  const formatted = authors.map((a) => {
    if (!a || !a.trim()) return "Anonim";
    const clean = a.trim();
    if (institutional.some((k) => clean.toLowerCase().includes(k))) return clean;
    if (clean.includes(",")) {
      const parts = clean.split(",");
      const surname = parts[0].trim();
      const initials = (parts[1] || "").trim().split(/\s+/).filter(Boolean).map((n) => n[0].toUpperCase() + ".").join(" ");
      return initials ? `${surname}, ${initials}` : surname;
    }
    const tokens = clean.split(/\s+/);
    if (tokens.length === 1) return clean;
    const surname = tokens[tokens.length - 1];
    const initials = tokens.slice(0, -1).map((n) => n[0].toUpperCase() + ".").join(" ");
    return initials ? `${surname}, ${initials}` : surname;
  });
  if (formatted.length === 1) return formatted[0];
  if (formatted.length === 2) return `${formatted[0]}, & ${formatted[1]}`;
  return `${formatted.slice(0, -1).join(", ")}, & ${formatted[formatted.length - 1]}`;
}

function formatAcademicReferenceText(ref, isEnDoc) {
  // Inisial seperti 'Cather, W.' sudah diakhiri titik, jadi titiknya dibuang di sini lalu ditambah sekali saat dirangkai
  const authorStr = formatAuthorsAPA(ref.authors).replace(/\.$/, "");
  const year = ref.year || "n.d.";
  const title = (ref.title || "Tanpa Judul").trim().replace(/\.+$/, "");
  const venue = (ref.venue || "").trim().replace(/\.+$/, "");
  let doi = (ref.doi || "").trim();
  if (doi && !doi.startsWith("http")) doi = `https://doi.org/${doi.replace(/^\/+/, "")}`;

  let pubDetails = "";
  const vol = (ref.volume || "").trim();
  const iss = (ref.issue || "").trim();
  const pgs = (ref.pages || "").trim();
  const pageInfo = (ref.page_info || "").trim().replace(/\.+$/, "");

  if (vol && iss && pgs) pubDetails = `${vol}(${iss}), ${pgs}`;
  else if (vol && pgs) pubDetails = `${vol}, ${pgs}`;
  else if (vol && iss) pubDetails = `${vol}(${iss})`;
  else if (pgs) pubDetails = `${isEnDoc ? "pp. " : "hlm. "}${pgs}`;
  else if (pageInfo) pubDetails = pageInfo;

  const parts = [`${authorStr}. (${year}). ${title}.`];
  if (venue && pubDetails) parts.push(`${venue}, ${pubDetails}.`);
  else if (venue) parts.push(`${venue}.`);
  else if (pubDetails) parts.push(`${pubDetails}.`);
  if (doi) parts.push(doi);

  return { authorStr, year, title, venue, pubDetails, doi, fullText: parts.join(" ") };
}

// ---------- Alert, toast, konfirmasi ----------
const UI = {
  showAlert(title, message, { type = "error", retry = null, retryLabel = "Coba lagi" } = {}) {
    const box = el("div", `alert ${type === "error" ? "alert-error" : "alert-success"}`);
    const icon = el("span");
    icon.innerHTML = type === "error" ? ICON.alert : ICON.success;
    const body = el("div", "flex-1 min-w-0");
    body.append(el("p", "alert-title", title), el("p", "alert-body", message));
    box.append(icon.firstChild, body);
    if (retry) {
      const btn = el("button", "btn btn-secondary px-3 py-1.5 text-xs shrink-0", retryLabel);
      btn.type = "button";
      btn.addEventListener("click", () => { UI.clearAlert(); retry(); });
      box.append(btn);
    }
    const close = el("button", "btn btn-ghost px-2 py-1.5 text-xs shrink-0", "Tutup");
    close.type = "button";
    close.addEventListener("click", UI.clearAlert);
    box.append(close);
    dom.alert.replaceChildren(box);
    dom.alert.classList.remove("hidden");
    dom.alert.scrollIntoView({ behavior: "smooth", block: "nearest" });
  },

  showError(title, err, retry) {
    const message = err instanceof ApiError ? err.message : "Terjadi kendala tak terduga. Coba ulangi sekali lagi.";
    UI.showAlert(title, message, { retry });
  },

  clearAlert() {
    dom.alert.classList.add("hidden");
    dom.alert.replaceChildren();
  },

  toast(message) {
    const node = el("div", "toast");
    node.innerHTML = ICON.check;
    node.append(document.createTextNode(message));
    dom.toastRegion.append(node);
    setTimeout(() => {
      node.classList.add("is-leaving");
      setTimeout(() => node.remove(), 220);
    }, 2600);
  },

  confirm({ title, message, okLabel = "Lanjutkan" }) {
    dom.confirmTitle.textContent = title;
    dom.confirmMessage.textContent = message;
    dom.confirmOk.textContent = okLabel;
    dom.confirmDialog.returnValue = "";
    dom.confirmDialog.showModal();
    dom.confirmOk.focus();
    return new Promise((resolve) => {
      dom.confirmDialog.addEventListener("close", () => resolve(dom.confirmDialog.returnValue === "ok"), { once: true });
    });
  },

  // ---------- Status Gemini ----------
  renderStatus(dotClass, label, model, hint) {
    dom.statusBadge.replaceChildren();
    dom.statusBadge.append(el("span", `status-dot ${dotClass}`), el("span", "", label));
    if (model) dom.statusBadge.append(el("span", "hidden md:inline font-mono text-[10px] text-ink-3", model));
    dom.statusBadge.title = hint;
  },

  // ---------- Stepper ----------
  renderStepper() {
    const steps = [
      { kicker: "Tahap 1", label: "Masukkan soal dan mode" },
      { kicker: "Tahap 2", label: "Kurasi sumber rujukan" },
      { kicker: "Tahap 3", label: "Studio naskah dan cetak" }
    ];
    dom.stepper.replaceChildren(...steps.map((item, idx) => {
      const n = idx + 1;
      const skipped = n === 2 && State.mode === "forum";
      const active = n === State.step;
      const done = !active && !skipped && n <= State.maxStep;
      const li = el("li", `step-item${active ? " is-active" : ""}${done ? " is-done" : ""}${skipped ? " is-skipped" : ""}`);
      const btn = el("button", "step-btn");
      btn.type = "button";
      btn.dataset.clickable = String(done);
      btn.disabled = !done;
      if (active) btn.setAttribute("aria-current", "step");
      const circle = el("span", "step-circle");
      circle.innerHTML = done ? ICON.check : String(n);
      const text = el("span", "step-text");
      text.append(el("span", "step-kicker", skipped ? "Dilewati" : item.kicker), el("span", "step-label", item.label));
      btn.append(circle, text);
      btn.setAttribute("aria-label", `${item.kicker}: ${item.label}${done ? ", selesai, klik untuk membuka" : skipped ? ", dilewati untuk jalur forum" : ""}`);
      if (done) btn.addEventListener("click", () => goStep(n));
      li.append(btn);
      return li;
    }));
  },

  showStep(n) {
    dom.steps.forEach((section, idx) => section.classList.toggle("hidden", idx + 1 !== n));
    UI.renderStepper();
    window.scrollTo({ top: 0, behavior: "smooth" });
  },

  // ---------- Soal ----------
  selectQuestionTab(tab) {
    const isUpload = tab === "upload";
    dom.tabType.setAttribute("aria-selected", String(!isUpload));
    dom.tabUpload.setAttribute("aria-selected", String(isUpload));
    dom.tabType.tabIndex = isUpload ? -1 : 0;
    dom.tabUpload.tabIndex = isUpload ? 0 : -1;
    dom.panelType.classList.toggle("hidden", isUpload);
    dom.panelUpload.classList.toggle("hidden", !isUpload);
    if (isUpload) UI.renderUploadPanel();
  },

  renderTopicMeta() {
    const text = dom.topic.value;
    dom.topicMeta.textContent = text.trim() ? `${formatNumber(countWords(text))} kata · ${formatNumber(text.length)} karakter` : "";
  },

  renderUploadPanel(loadingMessage) {
    const loading = Boolean(loadingMessage);
    const hasFile = Boolean(State.questionFileName && dom.topic.value.trim());
    dom.questionUploading.classList.toggle("hidden", !loading);
    dom.questionDropzone.classList.toggle("hidden", loading || hasFile);
    dom.questionPreview.classList.toggle("hidden", loading || !hasFile);
    if (loading) dom.questionUploadingText.textContent = loadingMessage;
    if (!loading && hasFile) UI.renderQuestionPreview(dom.topic.value);
  },

  renderQuestionPreview(text) {
    const ITEM_LINE = /^(\d{1,2})[.)]\s+(.*)$/;
    const OPTION_LINE = /^([a-hA-H])[.)]\s+(.*)$/;
    dom.questionPreviewBody.replaceChildren();
    let figures = 0;

    text.split(/(\[Gambar:[\s\S]*?\])/).forEach((part, index) => {
      if (index % 2 === 1) {
        figures += 1;
        const details = el("details", "ml-7 my-2 rounded-xl border border-line bg-subtle text-xs");
        const summary = el("summary", "cursor-pointer select-none px-3 py-2 font-semibold text-ink-2 rounded-xl", `Gambar ${figures} terbaca, buka untuk lihat isinya`);
        details.append(summary, el("p", "px-3 pb-3 leading-relaxed text-ink-2 whitespace-pre-line", part.replace(/^\[Gambar:\s*/, "").replace(/\]$/, "")));
        dom.questionPreviewBody.append(details);
        return;
      }
      part.split("\n").forEach((line) => {
        if (!line.trim()) return;
        const item = line.match(ITEM_LINE);
        const option = line.match(OPTION_LINE);
        const row = el("p");
        if (item) {
          row.className = "flex gap-2 pt-2 first:pt-0";
          row.append(el("span", "w-6 shrink-0 font-bold tabular-nums", `${item[1]}.`), el("span", "", item[2]));
        } else if (option) {
          row.className = "flex gap-2 pl-8 text-ink-2";
          row.append(el("span", "w-5 shrink-0 font-semibold", `${option[1]}.`), el("span", "", option[2]));
        } else {
          row.className = "text-ink-2";
          row.textContent = line;
        }
        dom.questionPreviewBody.append(row);
      });
    });

    dom.questionFileName.textContent = State.questionFileName;
    dom.questionCharBadge.textContent = `${formatNumber(text.length)} karakter`;
    const meta = [`${formatNumber(countWords(text))} kata`];
    if (figures) meta.push(`${figures} gambar terbaca`);
    dom.questionPreviewMeta.textContent = meta.join(" · ");
  },

  // ---------- Setelan ----------
  renderModeAction() {
    const mode = MODES[State.mode];
    dom.primaryLabel.textContent = mode.action;
    dom.primaryHint.textContent = mode.hint;
  },

  renderSummaries() {
    const tone = document.querySelector('input[name="tone"]:checked');
    dom.toneSummary.textContent = tone ? tone.closest("label").querySelector("b").textContent : "";

    const parts = [];
    const typeOption = dom.specAnswerType.selectedOptions[0];
    parts.push(dom.specAnswerType.value ? typeOption.textContent : "Otomatis");
    const count = readInt(dom.specQuestionCount);
    if (count) parts.push(`${count} soal`);
    const { total, items } = computeWordLimits();
    if (items && items.length) parts.push(`maks ${formatNumber(items[0])} kata per soal`);
    else if (total) parts.push(`maks ${formatNumber(total)} kata`);
    dom.specSummary.textContent = parts.join(" · ");

    const name = dom.studentName.value.trim();
    const nim = dom.studentId.value.trim();
    dom.identitySummary.textContent = name || nim ? [name, nim].filter(Boolean).join(" · ") : "Belum diisi";
  },

  renderWordSummary() {
    const { total, items, error } = computeWordLimits();
    const isDirect = DIRECT_ANSWER_TYPES.includes(dom.specAnswerType.value);
    dom.specWordLimit.setAttribute("aria-invalid", error ? "true" : "false");
    dom.specWordSummary.classList.toggle("text-danger-text", Boolean(error));

    let text;
    if (error) {
      text = error;
    } else if (State.detectedItemLimits && !dom.specWordLimit.value) {
      const list = State.detectedItemLimits.map((n, i) => `soal ${i + 1}: ${n ? `maksimal ${formatNumber(n)} kata` : "tanpa batas atas"}`).join(", ");
      text = `Batas dari dosen berbeda tiap soal, ${list}.${total ? ` Total ${formatNumber(total)} kata.` : ""}`;
    } else if (items && items.length > 1) {
      text = `${items.length} soal kali ${formatNumber(items[0])} kata, total ${formatNumber(total || items[0] * items.length)} kata. Tiap soal dijaga tidak lewat batas.`;
    } else if (items) {
      text = `Tiap soal maksimal ${formatNumber(items[0])} kata. Isi jumlah soal supaya totalnya dihitung.`;
    } else if (total) {
      text = `Maksimal ${formatNumber(total)} kata untuk seluruh jawaban.`;
    } else if (isDirect) {
      text = "Tidak ada batas dari dosen. Panjang tiap butir menyesuaikan pertanyaannya.";
    } else {
      text = "Tidak ada batas dari dosen. Panjang mengikuti target panjang.";
    }
    dom.specWordSummary.textContent = text;
    return { total, error };
  },

  // Opsi yang tidak berpengaruh untuk jenis jawaban terpilih disembunyikan agar form tidak membingungkan
  renderSpecVisibility() {
    const type = dom.specAnswerType.value;
    const isDirect = DIRECT_ANSWER_TYPES.includes(type);
    const { total } = UI.renderWordSummary();
    const hideFormat = FORMAT_DECIDED_TYPES.includes(type);
    dom.formatWrapper.classList.toggle("hidden", hideFormat);
    if (hideFormat) setRadio("format", "otomatis");
    dom.detailsTone.classList.toggle("hidden", isDirect);
    // Target panjang tetap bisa dipilih selama batas total dosen belum pasti
    const hideTarget = isDirect || Boolean(total);
    dom.lengthWrapper.classList.toggle("hidden", hideTarget);
    dom.customWordsWrapper.classList.toggle("hidden", hideTarget || dom.selectLength.value !== "kustom");
    UI.renderSummaries();
  },

  renderSpecNote() {
    if (!State.specSource) {
      dom.specNote.textContent = "Terisi otomatis saat lembar soal diunggah. Koreksi di sini jika ada yang keliru.";
      return;
    }
    dom.specNote.textContent = (State.specSource === "ai"
      ? "Dideteksi AI dari lembar soal. Cek sekali lagi sebelum lanjut."
      : "AI sedang tidak tersedia, jadi ini tebakan dari pola teks soal. Mohon dicek ulang.")
      + (State.detectedSections ? ` Format wajib: ${State.detectedSections.join(", ")}.` : "");
  },

  // ---------- Tahap 2 ----------
  renderStep2() {
    const isBahan = State.mode === "bahan";
    dom.panelBahan.classList.toggle("hidden", !isBahan);
    dom.panelJurnal.classList.toggle("hidden", isBahan);
    dom.step2Title.textContent = isBahan ? "Studio bahan bacaan dosen" : "Kurasi jurnal ilmiah terbuka";
    dom.step2Lede.textContent = isBahan
      ? "Unggah naskah yang diberikan dosen, lengkapi keterangannya, lalu periksa potongan teks yang akan dibaca saat menyusun jawaban."
      : "Centang artikel yang mau disitir. Teks asli artikel terpilih dibaca lalu dikutip nyata ke dalam naskah.";
    if (isBahan) {
      UI.renderMaterialPreview();
      UI.renderMaterialList();
      loadAndRenderSavedModules();
    } else if (!State.papers.length && dom.papersLoading.classList.contains("hidden")) {
      UI.renderPapersEmpty("Tekan Cari jurnal untuk mulai mencari artikel yang relevan.");
    }
    UI.renderSelection();
  },

  renderSelection() {
    const isBahan = State.mode === "bahan";
    const count = isBahan ? State.materials.length : State.selectedPaperIds.size;
    dom.selectedCount.textContent = String(count);
    dom.selectedHint.textContent = isBahan
      ? (count ? `${count} bahan siap dibaca` : "Simpan minimal satu bahan, atau isi formulir lalu langsung tulis")
      : (count ? `${count} rujukan terpilih untuk disitir` : "Belum ada rujukan dicentang, naskah ditulis tanpa sitasi jurnal");
  },

  renderPapersLoading(loading) {
    dom.papersLoading.classList.toggle("hidden", !loading);
    if (loading) dom.papersList.replaceChildren();
  },

  renderPapersEmpty(message, query) {
    const box = el("li", "empty-state");
    box.innerHTML = ICON.search;
    box.append(
      el("p", "text-sm font-bold", "Belum ada artikel yang cocok"),
      el("p", "text-xs text-ink-2 mt-1 max-w-md mx-auto", message || "Coba kata kunci yang lebih ringkas, atau masukkan DOI jika sudah punya artikel tertentu.")
    );
    if (query) box.append(el("p", "text-[11px] text-ink-3 mt-3", `Kata kunci yang diproses: ${query}`));
    dom.papersList.replaceChildren(box);
  },

  renderPapers() {
    if (!State.papers.length) return UI.renderPapersEmpty();
    dom.papersList.replaceChildren(...State.papers.map((paper) => {
      const li = el("li");
      const card = el("label", "paper-card");
      const check = el("input", "paper-check");
      check.type = "checkbox";
      check.checked = State.selectedPaperIds.has(paper.id);
      check.setAttribute("aria-label", `Pilih ${paper.title}`);
      check.addEventListener("change", () => togglePaper(paper.id, check.checked));

      const body = el("div", "flex-1 min-w-0");
      const meta = el("div", "flex flex-wrap items-center gap-2 mb-1.5");
      meta.append(el("span", "count-badge", paper.year ? String(paper.year) : "t.t."));
      if (paper.venue) meta.append(el("span", "text-[11px] font-semibold text-ink-2 truncate max-w-[22rem]", paper.venue));
      const oa = el("span", "oa-badge", paper.is_ut_bmp ? "Modul UT" : "Akses terbuka");
      meta.append(oa);

      const authors = (paper.authors || []).slice(0, 3).join(", ") + ((paper.authors || []).length > 3 ? " dkk." : "");
      body.append(meta, el("h3", "text-sm font-bold leading-snug", paper.title));
      if (authors) body.append(el("p", "text-xs text-ink-2 mt-1", authors));

      const links = el("div", "mt-3 flex flex-wrap items-center gap-4");
      if (paper.abstract) {
        const abstract = el("p", "hidden mt-3 text-xs leading-relaxed text-ink-2 max-w-prose", paper.abstract);
        abstract.id = `abstract-${paper.id}`;
        const toggle = el("button", "abstract-toggle", "Pratinjau abstrak");
        toggle.type = "button";
        toggle.setAttribute("aria-expanded", "false");
        toggle.setAttribute("aria-controls", abstract.id);
        toggle.addEventListener("click", (e) => {
          e.preventDefault();
          const open = abstract.classList.toggle("hidden") === false;
          toggle.setAttribute("aria-expanded", String(open));
          toggle.textContent = open ? "Tutup abstrak" : "Pratinjau abstrak";
        });
        links.append(toggle);
        body.append(links, abstract);
      } else {
        body.append(links);
      }
      [[paper.doi, "DOI"], [paper.scholar_url, "Halaman asli"]].forEach(([href, label]) => {
        if (!href || !/^https?:\/\//.test(href)) return;
        const a = el("a", "abstract-toggle text-ink-2", label);
        a.href = href;
        a.target = "_blank";
        a.rel = "noopener";
        a.addEventListener("click", (e) => e.stopPropagation());
        links.append(a);
      });

      card.append(check, body);
      li.append(card);
      return li;
    }));
  },

  renderMaterialMeta() {
    const text = dom.materialText.value;
    dom.materialTextMeta.textContent = text.trim() ? `${formatNumber(countWords(text))} kata · ${formatNumber(text.length)} karakter` : "";
  },

  renderMaterialPreview() {
    UI.renderMaterialMeta();
    const chunks = splitMarkedPages(dom.materialText.value)
      .flatMap(({ label, body }) => chunkParagraphs(body).map((text) => ({ label, text })));
    dom.materialChunkCount.textContent = chunks.length ? `${chunks.length} bagian` : "";
    if (!chunks.length) {
      const empty = el("li", "empty-state !py-8");
      empty.innerHTML = ICON.book;
      empty.append(
        el("p", "text-sm font-bold", "Belum ada naskah"),
        el("p", "text-xs text-ink-2 mt-1", "Potongan bagian muncul di sini setelah berkas dibaca atau teks ditempel.")
      );
      dom.materialChunks.replaceChildren(empty);
      return;
    }
    const shown = chunks.slice(0, 6).map((chunk, i) => {
      const li = el("li", "flex gap-3 p-3 rounded-xl border border-line bg-subtle");
      const body = el("div", "min-w-0");
      // Label halaman asli dipakai model untuk sitasi hlm., jadi ditampilkan supaya bisa dicek
      if (chunk.label) body.append(el("p", "text-[11px] font-semibold text-ink-3 mb-1 tabular-nums", chunk.label));
      body.append(el("p", "text-xs leading-relaxed text-ink-2 line-clamp-3", chunk.text));
      li.append(el("span", "font-serif italic text-ink-3 text-sm w-6 shrink-0 tabular-nums", String(i + 1).padStart(2, "0")), body);
      return li;
    });
    if (chunks.length > 6) shown.push(el("li", "text-[11px] text-ink-3 pl-9", `dan ${chunks.length - 6} bagian lainnya ikut dibaca`));
    dom.materialChunks.replaceChildren(...shown);
  },

  renderMaterialList() {
    if (!State.materials.length) {
      dom.materialList.replaceChildren(el("li", "text-xs text-ink-3 leading-relaxed", "Belum ada bahan tersimpan. Bahan di formulir tetap ikut dibaca saat menulis naskah."));
      return;
    }
    dom.materialList.replaceChildren(...State.materials.map((m) => {
      const li = el("li", "flex items-start gap-2 p-3 rounded-xl border border-ok-line bg-ok-bg");
      const body = el("div", "flex-1 min-w-0");
      body.append(el("p", "text-xs font-bold text-ok-text truncate", m.title));
      const meta = [(m.authors || []).join(", "), m.year].filter(Boolean).join(", ");
      if (meta) body.append(el("p", "text-[11px] text-ok-text opacity-80 truncate", meta));
      const remove = el("button", "btn btn-ghost p-1.5 shrink-0");
      remove.type = "button";
      remove.innerHTML = ICON.trash;
      remove.firstChild.setAttribute("class", "w-3.5 h-3.5");
      remove.setAttribute("aria-label", `Hapus ${m.title}`);
      remove.addEventListener("click", () => removeMaterial(m.id));
      li.append(body, remove);
      return li;
    }));
  },

  renderUtResult(data, onApply) {
    const box = dom.materialUtResult;
    if (!data) {
      box.classList.add("hidden");
      box.replaceChildren();
      return;
    }
    box.classList.remove("hidden");
    const wrap = el("div", "p-3 rounded-xl border border-ok-line bg-ok-bg text-xs text-ok-text");
    if (data.exact) {
      const row = el("div", "flex items-center justify-between gap-2 flex-wrap");
      const info = el("p", "font-semibold", `Terdeteksi modul resmi UT: ${data.course.kode} ${data.course.nama}, ${data.course.edisi}`);
      const btn = el("button", "btn btn-primary px-3 py-1.5 text-[11px]", "Pakai judul resmi");
      btn.type = "button";
      btn.addEventListener("click", () => onApply(data.course));
      row.append(info, btn);
      wrap.append(row);
    } else {
      wrap.append(el("p", "font-semibold mb-2", "Mata kuliah UT yang mirip:"));
      const pills = el("div", "flex flex-wrap gap-1.5");
      data.suggestions.forEach((s) => {
        const pill = el("button", "btn btn-secondary px-2.5 py-1 text-[11px]", `${s.kode} ${s.nama}`);
        pill.type = "button";
        pill.addEventListener("click", () => onApply(s));
        pills.append(pill);
      });
      wrap.append(pills);
    }
    box.replaceChildren(wrap);
  },

  // ---------- Tahap 3 ----------
  renderPipeline(active) {
    dom.pipeline.querySelectorAll("li").forEach((li) => {
      const n = Number(li.dataset.pipe);
      li.classList.toggle("is-done", n < active);
      li.classList.toggle("is-active", n === active);
    });
  },

  renderGenerating(on) {
    dom.generating.classList.toggle("hidden", !on);
    dom.result.classList.toggle("hidden", on || !State.doc);
  },

  renderStats() {
    const refs = State.doc.references.length;
    dom.resultStats.textContent = `Sekitar ${formatNumber(State.doc.wordCount)} kata · ${refs ? `${refs} rujukan terverifikasi` : "tanpa rujukan"}`;
  },

  renderEvidence(evidence) {
    const list = evidence || [];
    dom.evidence.classList.toggle("hidden", !list.length);
    dom.evidenceCount.textContent = list.length ? `${list.length} sumber` : "";
    dom.evidenceList.replaceChildren(...list.map((ev) => {
      const item = el("div", "p-4 rounded-xl border border-line bg-subtle");
      const badges = el("div", "flex flex-wrap items-center gap-2 mb-1.5");
      badges.append(el("span", ev.has_full_pdf ? "oa-badge" : "count-badge", ev.has_full_pdf ? "Teks lengkap terbaca" : "Abstrak dan metadata"));
      if (ev.citation_count > 0) badges.append(el("span", "count-badge", `${ev.citation_count} kali disitir`));
      badges.append(el("span", "text-[11px] text-ink-3", [ev.venue, ev.year || "t.t."].filter(Boolean).join(", ")));
      item.append(badges, el("p", "text-sm font-bold leading-snug", ev.title), el("p", "text-xs text-ink-2 mt-0.5", ev.authors));
      (ev.snippets || []).forEach((sn) => {
        const quote = el("blockquote", "mt-2 pl-3 border-l-2 border-edge text-xs leading-relaxed text-ink-2");
        const where = typeof sn.page === "number" ? `Hlm. ${sn.page}` : sn.page;
        quote.append(el("span", "font-semibold text-ink", `${where}. `), document.createTextNode(sn.text));
        item.append(quote);
      });
      return item;
    }));
  },

  renderDocument() {
    const doc = State.doc;
    dom.resultTitle.textContent = doc.title;
    UI.renderStats();
    dom.paper.replaceChildren(UI.buildTitleBlock());
    if (doc.identityLines.length) {
      const identity = el("div", "paper-identity");
      doc.identityLines.forEach((line) => identity.append(el("div", "", line)));
      dom.paper.append(identity);
    } else {
      dom.paper.append(el("div", "h-8"));
    }
    doc.sections.forEach((sec, index) => dom.paper.append(UI.buildSectionBlock(sec, index)));
    if (doc.references.length) dom.paper.append(UI.buildReferencesBlock());
  },

  docButton(label, primary, onClick, ariaLabel) {
    const node = el("button", primary ? "doc-btn doc-btn-primary" : "doc-btn", label);
    node.type = "button";
    if (ariaLabel) node.setAttribute("aria-label", ariaLabel);
    node.disabled = State.docBusy;
    node.addEventListener("click", onClick);
    return node;
  },

  buildTitleBlock() {
    const wrap = el("div", "paper-title-wrap relative");
    const tools = el("div", "doc-tools justify-center mb-2");
    tools.append(UI.docButton("Ubah judul", false, () => UI.openTitleEditor(wrap), "Ubah judul naskah"));
    wrap.append(tools, el("h2", "paper-title", State.doc.title));
    return wrap;
  },

  openTitleEditor(wrap) {
    const input = el("input", "doc-field text-center font-bold");
    input.value = State.doc.title;
    input.maxLength = 300;
    input.setAttribute("aria-label", "Judul naskah");
    const save = () => {
      const title = input.value.trim();
      if (!title) return input.focus();
      saveDocument({ title, sections: State.doc.sections }, wrap);
    };
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") save();
      if (e.key === "Escape") UI.renderDocument();
    });
    const actions = el("div", "flex justify-center gap-2 mt-2");
    actions.append(UI.docButton("Batal", false, UI.renderDocument), UI.docButton("Simpan", true, save));
    wrap.replaceChildren(input, actions);
    input.focus();
  },

  buildSectionBlock(sec, index) {
    const article = el("section", "doc-section");
    const label = sec.heading && sec.heading.trim() ? sec.heading : `Bagian ${index + 1}`;
    const head = el("div", "flex items-start justify-between gap-3");
    head.append(sec.heading ? el("h3", "paper-heading", sec.heading) : el("span"));
    const tools = el("div", "doc-tools shrink-0");
    tools.append(
      UI.docButton("Edit", false, () => UI.openSectionEditor(article, index), `Edit ${label}`),
      UI.docButton("Tulis ulang", false, () => UI.openRewriteForm(article, index), `Tulis ulang ${label}`)
    );
    const history = State.sectionHistory[index] || [];
    if (history.length) {
      tools.append(UI.docButton("Kembalikan", false, () => restoreSection(article, index),
        `Kembalikan ${label} ke versi sebelumnya, tersisa ${history.length} versi`));
    }
    head.append(tools);
    const body = el("div", "section-body");
    UI.fillParagraphs(body, sec.content);
    article.append(head, body);
    return article;
  },

  // Satu baris naskah jadi satu alinea. Butir bernomor dan daftar tidak diberi indentasi.
  fillParagraphs(container, content) {
    const LIST_LINE = /^(\d{1,2}[.)]|[a-hA-H][.)]|[-•*])\s/;
    container.replaceChildren(...(content || "").split(/\n+/).filter((l) => l.trim()).map((line) => {
      const p = el("p", LIST_LINE.test(line.trim()) ? "no-indent" : "");
      UI.appendWithCitations(p, line.trim());
      return p;
    }));
  },

  // Sitasi seperti (Navis, 1956) jadi penanda yang bisa diklik untuk loncat ke daftar pustaka
  appendWithCitations(node, text) {
    const CITE = /\(([^()]*?(?:\d{4}[a-z]?|n\.d\.|t\.t\.)[^()]*?)\)/g;
    let last = 0;
    for (const match of text.matchAll(CITE)) {
      node.append(document.createTextNode(text.slice(last, match.index)));
      const refIndex = findReferenceIndex(match[1]);
      if (refIndex === -1) {
        node.append(document.createTextNode(match[0]));
      } else {
        const cite = el("button", "cite", match[0]);
        cite.type = "button";
        cite.title = "Lihat sumber di daftar pustaka";
        cite.addEventListener("click", () => UI.flashReference(refIndex));
        node.append(cite);
      }
      last = match.index + match[0].length;
    }
    node.append(document.createTextNode(text.slice(last)));
  },

  flashReference(index) {
    const item = dom.paper.querySelector(`[data-ref-index="${index}"]`);
    if (!item) return;
    item.scrollIntoView({ behavior: "smooth", block: "center" });
    item.classList.add("is-flash");
    setTimeout(() => item.classList.remove("is-flash"), 1600);
  },

  buildReferencesBlock() {
    // Bahasa diambil dari generator. Menebak dari kata 'the' salah untuk naskah Indonesia yang memuat kutipan bahasa Inggris.
    const isEnDoc = State.doc.language === "en";
    const block = el("div", "paper-refs");
    block.append(el("h3", "paper-heading", isEnDoc ? "References" : "Daftar Pustaka"));
    const list = el("ol");
    State.doc.references.forEach((ref, i) => {
      const data = formatAcademicReferenceText(ref, isEnDoc);
      const li = el("li");
      li.dataset.refIndex = String(i);

      li.append(document.createTextNode(`${data.authorStr}. (${data.year}). ${data.title}.`));
      if (data.venue) {
        li.append(document.createTextNode(" "));
        const em = el("em", "italic", data.venue);
        li.append(em);
      }
      if (data.pubDetails) {
        li.append(document.createTextNode(`${data.venue ? ", " : " "}${data.pubDetails}.`));
      } else if (data.venue) {
        li.append(document.createTextNode("."));
      }
      if (data.doi) {
        li.append(document.createTextNode(" "));
        const a = el("a", "underline text-stone-600 dark:text-stone-300 hover:text-stone-900 dark:hover:text-stone-100", data.doi);
        a.href = data.doi;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        li.append(a);
      }
      list.append(li);
    });
    block.append(list);
    return block;
  },

  showSectionError(container, message) {
    container.querySelectorAll(".doc-error").forEach((node) => node.remove());
    const error = el("p", "doc-error", message);
    error.setAttribute("role", "alert");
    container.append(error);
  },

  openSectionEditor(article, index) {
    const sec = State.doc.sections[index];
    const headingInput = el("input", "doc-field font-bold");
    headingInput.value = sec.heading || "";
    headingInput.maxLength = 500;
    headingInput.setAttribute("aria-label", "Judul bagian");
    const contentInput = el("textarea", "doc-field resize-y");
    contentInput.value = sec.content;
    contentInput.rows = Math.min(24, Math.max(6, Math.ceil(sec.content.length / 90) + sec.content.split("\n").length));
    contentInput.setAttribute("aria-label", "Isi bagian");
    const meta = el("span", "font-sans text-[11px] text-stone-500 tabular-nums");
    const updateMeta = () => { meta.textContent = `${countWords(contentInput.value)} kata`; };
    contentInput.addEventListener("input", updateMeta);
    updateMeta();

    const save = () => {
      if (!contentInput.value.trim()) {
        UI.showSectionError(article, "Isi bagian tidak boleh kosong.");
        return contentInput.focus();
      }
      const sections = State.doc.sections.map((s, i) => i === index ? { heading: headingInput.value.trim(), content: contentInput.value.trim() } : s);
      saveDocument({ title: State.doc.title, sections }, article, index);
    };
    contentInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) save();
      if (e.key === "Escape") UI.renderDocument();
    });

    const actions = el("div", "flex items-center justify-between gap-2");
    const buttons = el("div", "flex gap-2");
    buttons.append(UI.docButton("Batal", false, UI.renderDocument), UI.docButton("Simpan bagian", true, save));
    actions.append(meta, buttons);
    const form = el("div", "space-y-2");
    form.append(headingInput, contentInput, actions);
    article.replaceChildren(form);
    contentInput.focus();
  },

  openRewriteForm(article, index) {
    if (article.querySelector(".rewrite-form")) return;
    const form = el("div", "rewrite-form font-sans mt-3 p-3 rounded-lg bg-stone-50 border border-stone-200 space-y-2");
    const input = el("input", "doc-field");
    input.maxLength = 500;
    input.placeholder = "Arahan opsional, misalnya lebih santai, persingkat, tambah contoh";
    input.setAttribute("aria-label", "Arahan tulis ulang");
    const run = () => rewriteSection(article, index, input.value.trim());
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") run();
      if (e.key === "Escape") form.remove();
    });
    const actions = el("div", "flex justify-end gap-2");
    actions.append(UI.docButton("Batal", false, () => form.remove()), UI.docButton("Tulis ulang bagian ini", true, run));
    form.append(input, actions);
    article.append(form);
    input.focus();
  },

  setDocBusy(busy) {
    State.docBusy = busy;
    dom.paper.setAttribute("aria-busy", String(busy));
    dom.paper.querySelectorAll("button, input, textarea").forEach((node) => { node.disabled = busy; });
    dom.btnRegenerate.disabled = busy;
  }
};

// =====================================================================
// 4. LOGIKA MURNI
// =====================================================================

// Satu pencarian Google lewat Gemini per klik. Hasil hanya mengisi kolom yang masih kosong supaya isian pengguna tidak ditimpa.
async function lookupPublicationInfo() {
  const title = dom.materialTitle.value.trim();
  const box = dom.publicationResult;
  if (title.length < 3) {
    dom.materialTitle.focus();
    UI.toast("Isi judul naskah dulu");
    return;
  }
  setBusy(dom.btnLookupPublication, true, "Mencari");
  box.classList.remove("hidden");
  box.replaceChildren(el("p", "animate-pulse", "Mencari info terbit pertama di internet..."));
  try {
    const data = await Api.lookupPublication(title, dom.materialAuthor.value.trim());
    if (!data.found) {
      box.replaceChildren(el("p", "", data.note || "Info terbit tidak ditemukan. Isi manual dari sampul atau halaman hak cipta naskah."));
      return;
    }
    const filled = [];
    [[dom.materialAuthor, data.author, "penulis"], [dom.materialYear, data.year, "tahun"], [dom.materialPublisher, data.venue, "tempat terbit"]]
      .forEach(([input, value, name]) => {
        if (value && !input.value.trim()) {
          input.value = value;
          filled.push(name);
        }
      });
    UI.renderMaterialMeta();
    const facts = [data.author, data.year, data.venue].filter(Boolean).join(" · ");
    const children = [
      el("p", "font-semibold text-ink", facts),
      el("p", "mt-1", data.note),
      el("p", "mt-1 text-ink-3", filled.length
        ? `Terisi otomatis: ${filled.join(", ")}. Cek dulu sebelum simpan, hasil pencarian bisa meleset.`
        : "Kolom sudah terisi, jadi tidak ditimpa. Bandingkan dengan isianmu.")
    ];
    const list = el("ul", "mt-2 space-y-0.5");
    data.sources.forEach((src) => {
      const a = el("a", "underline underline-offset-2 hover:text-ink break-all", src.title);
      a.href = src.uri;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      const li = el("li");
      li.append(a);
      list.append(li);
    });
    children.push(el("p", "mt-2 font-semibold text-ink-3", "Sumber"), list);
    box.replaceChildren(...children);
  } catch (err) {
    box.replaceChildren(el("p", "text-danger-text", err.message || "Pencarian gagal. Isi tahun manual dulu."));
  } finally {
    setBusy(dom.btnLookupPublication, false);
  }
}

// Mencari baris penulis seperti 'by Willa Cather' atau 'oleh A.A. Navis' di awal naskah, judulnya baris tepat di atasnya
function findByline(text) {
  const lines = (text || "").split("\n").map((ln) => ln.trim()).filter((ln) => ln && !/^\[Halaman \d+\]$/.test(ln)).slice(0, 8);
  for (let i = 0; i < lines.length; i++) {
    // Nama wajib berhuruf besar supaya kalimat seperti 'by the river' tidak dianggap nama penulis
    const match = lines[i].match(/^(?:[Bb]y|[Oo]leh|[Kk]arya)\s+([A-Z][A-Za-z.'-]*(?:\s+[A-Z][A-Za-z.'-]*){0,4})$/);
    if (!match) continue;
    const prev = i > 0 ? lines[i - 1] : "";
    return { author: match[1].trim(), title: prev.length >= 3 && prev.length <= 120 ? prev : "" };
  }
  return null;
}

// Mengikuti split_marked_pages di tools/reading_doc_reader.py: penanda [Halaman n] dari PDF jadi label halaman
function splitMarkedPages(text) {
  const parts = (text || "").split(/^\[Halaman (\d+)\][ \t]*$/m);
  const pages = parts[0].trim() ? [{ label: "", body: parts[0] }] : [];
  for (let i = 1; i < parts.length; i += 2) {
    if ((parts[i + 1] || "").trim()) pages.push({ label: `Halaman ${parts[i]}`, body: parts[i + 1] });
  }
  return pages;
}

// Mengikuti tools/content_chunker.py supaya pratinjau sama dengan potongan yang disimpan server
function chunkParagraphs(text, maxChars = 3000) {
  const clean = (text || "").replace(/\r\n?/g, "\n").trim();
  if (!clean) return [];
  const pieces = [];
  clean.split(/\n\s*\n/).map((p) => p.split(/\s+/).join(" ").trim()).filter(Boolean).forEach((para) => {
    while (para.length > maxChars) {
      let cut = para.lastIndexOf(". ", maxChars);
      cut = cut > maxChars / 2 ? cut + 1 : maxChars;
      pieces.push(para.slice(0, cut).trim());
      para = para.slice(cut).trim();
    }
    if (para) pieces.push(para);
  });
  const chunks = [];
  pieces.forEach((piece) => {
    if (chunks.length && chunks[chunks.length - 1].length + 2 + piece.length <= maxChars) {
      chunks[chunks.length - 1] += "\n\n" + piece;
    } else {
      chunks.push(piece);
    }
  });
  return chunks;
}

// Blok gambar yang menempel di tengah kalimat soal dipindah ke bawah kalimatnya agar nomor soal tidak terpotong
function detachFigures(text) {
  const inline = /^(.*?)[ \t]*(\[Gambar:[^\]]*\])[ \t]*(.*)$/gm;
  for (let i = 0; i < 10; i += 1) {
    const next = text.replace(inline, (match, before, figure, after) => {
      const rest = `${before} ${after}`.trim();
      return rest ? `${rest}\n${figure}` : figure;
    });
    if (next === text) break;
    text = next;
  }
  return text;
}

// Merapikan teks soal: satu baris kosong sebelum tiap nomor dan tiap blok gambar, spasi berlebih dibuang
function formatQuestionText(raw) {
  const ITEM_LINE = /^(\d{1,2})[.)]\s+(.*)$/;
  const lines = detachFigures((raw || "").replace(/\r\n?/g, "\n").replace(/\t/g, " "))
    .split("\n")
    .map((line) => line.trim());
  const out = [];
  lines.forEach((line) => {
    const startsBlock = ITEM_LINE.test(line) || line.startsWith("[Gambar:");
    if (startsBlock && out.length && out[out.length - 1] !== "") out.push("");
    out.push(line);
  });
  return out.join("\n").replace(/\n{3,}/g, "\n\n").trim();
}

function computeWordLimits() {
  const count = readInt(dom.specQuestionCount);
  const validCount = count >= 1 && count <= 50 ? count : null;
  const limit = readInt(dom.specWordLimit);
  const items = State.detectedItemLimits;

  if (items && limit === null) {
    // Butir tanpa batas atas bikin total tidak bisa dihitung
    const bounded = items.every((n) => n);
    const total = items.reduce((sum, n) => sum + (n || 0), 0);
    return { total: bounded && total <= 10000 ? total : null, items, error: null };
  }
  if (limit === null) return { total: null, items: null, error: null };

  if (dom.specWordScope.value === "total") {
    if (limit < 50 || limit > 10000) return { total: null, items: null, error: "Batas total harus 50 sampai 10.000 kata." };
    return { total: limit, items: null, error: null };
  }
  if (limit < 10 || limit > 5000) return { total: null, items: null, error: "Batas per soal harus 10 sampai 5.000 kata." };
  if (!validCount) return { total: null, items: [limit], error: null };
  const total = limit * validCount;
  return { total: total <= 10000 ? total : null, items: Array(validCount).fill(limit), error: null };
}

function readAnswerSpec() {
  const count = readInt(dom.specQuestionCount);
  const { total, items } = computeWordLimits();
  return {
    question_count: count >= 1 && count <= 50 ? count : null,
    answer_type: dom.specAnswerType.value || null,
    needs_citations: State.mode !== "forum",
    answer_language: dom.specLanguage.value || null,
    word_limit: total,
    item_word_limits: items,
    required_sections: State.detectedSections
  };
}

function targetWords() {
  const choice = dom.selectLength.value;
  let words = choice === "kustom" ? (parseInt(dom.customWords.value, 10) || 1200) : (LENGTH_WORDS[choice] || 950);
  // Batas total dari dosen menggantikan target, dibatasi rentang yang diterima server
  const lecturerTotal = computeWordLimits().total;
  if (lecturerTotal) words = lecturerTotal;
  return Math.min(5000, Math.max(200, words));
}

function buildGeneratePayload(paperIds) {
  let format = radioValue("format") || "otomatis";
  // Jalur forum menulis jawaban mengalir tanpa bab kecuali mahasiswa memilih format lain
  if (State.mode === "forum" && format === "otomatis" && !dom.specAnswerType.value) format = "esai";
  return {
    topic: dom.topic.value.trim(),
    format_type: format,
    target_length: dom.selectLength.value,
    target_words: targetWords(),
    paragraph_depth: dom.selectDepth.value,
    tone: radioValue("tone") || "akademis formal",
    paper_ids: paperIds,
    custom_instructions: dom.instructions.value.trim(),
    answer_spec: readAnswerSpec(),
    quote_citations: dom.quoteCitations.checked,
    student_name: dom.studentName.value.trim(),
    student_id: dom.studentId.value.trim(),
    course_name: dom.courseName.value.trim()
  };
}

// Mencocokkan isi sitasi dengan nama belakang penulis di daftar pustaka
function findReferenceIndex(citation) {
  if (!State.doc) return -1;
  const lower = citation.toLowerCase();
  return State.doc.references.findIndex((ref) => (ref.authors || []).some((name) => {
    const surname = name.trim().split(/\s+/).pop() || "";
    return surname.length > 1 && lower.includes(surname.toLowerCase().replace(/[.,]/g, ""));
  }));
}

function documentAsText() {
  const doc = State.doc;
  const out = [doc.title.toUpperCase(), ""];
  if (doc.identityLines.length) out.push(...doc.identityLines, "");
  doc.sections.forEach((sec) => {
    if (sec.heading) out.push(sec.heading);
    out.push(sec.content, "");
  });
  if (doc.references.length) {
    const isEn = State.doc.language === "en";
    out.push(isEn ? "REFERENCES" : "DAFTAR PUSTAKA", "");
    doc.references.forEach((ref) => {
      const data = formatAcademicReferenceText(ref, isEn);
      out.push(data.fullText);
    });
  }
  return out.join("\n").trim();
}

// =====================================================================
// 5. ALUR APLIKASI
// =====================================================================

function goStep(n) {
  State.step = n;
  State.maxStep = Math.max(State.maxStep, n);
  UI.clearAlert();
  UI.showStep(n);
  if (n === 2) UI.renderStep2();
}

function setMode(mode) {
  if (!MODES[mode]) return;
  State.mode = mode;
  setRadio("mode", mode);
  storage.set(STORAGE.mode, mode);
  UI.renderModeAction();
  UI.renderStepper();
}

// ---------- Health check ----------
// Status dicek ulang berkala. Saat jeda, hitung mundur jalan tiap detik lalu dicek lagi begitu habis.
const HEALTH_POLL_MS = 20000;
let healthTimer = null;

function startCooldownCountdown(seconds, model) {
  let left = seconds;
  const tick = () => {
    if (left <= 0) return checkSystemHealth();
    UI.renderStatus("is-paused is-breathing", `Gemini jeda ${left} dtk`, model, "Google sedang membatasi permintaan. Tunggu hitungan selesai sebelum menulis naskah.");
    left -= 1;
    healthTimer = setTimeout(tick, 1000);
  };
  tick();
}

async function checkSystemHealth() {
  clearTimeout(healthTimer);
  try {
    const data = await Api.health();
    if (data.ai_state === "cooldown") return startCooldownCountdown(data.retry_in || 30, data.active_model);
    if (data.ai_state === "ready") {
      UI.renderStatus("is-ready is-breathing", "Gemini siap", data.active_model, `Model aktif otomatis: ${data.active_model}`);
    } else if (data.ai_state === "unavailable") {
      UI.renderStatus("is-down", "Model tidak tersedia", null, "Semua model Gemini menolak akun ini. Cek kuota atau API key di Google AI Studio.");
    } else {
      UI.renderStatus("is-paused", "API key belum disetel", null, "Isi GEMINI_API_KEY di berkas .env lalu buka ulang aplikasi.");
    }
  } catch (err) {
    UI.renderStatus("is-down", "Server offline", null, "Server lokal tidak merespons.");
  }
  healthTimer = setTimeout(checkSystemHealth, HEALTH_POLL_MS);
}

// ---------- Soal ----------
let draftTimer = null;
function saveDraft() {
  clearTimeout(draftTimer);
  draftTimer = setTimeout(() => {
    const text = dom.topic.value;
    if (text.trim()) {
      storage.set(STORAGE.draft, text);
      dom.draftStatus.textContent = "Draf tersimpan otomatis";
    } else {
      storage.remove(STORAGE.draft);
      dom.draftStatus.textContent = "";
    }
    storage.set(STORAGE.draftSetup, JSON.stringify({
      instructions: dom.instructions.value,
      spec: readAnswerSpec(),
      source: State.specSource
    }));
  }, 400);
}

function setQuestionText(text) {
  dom.topic.value = text;
  UI.renderTopicMeta();
  saveDraft();
}

function applyAnswerSpec(spec, source) {
  if (!spec) return;
  dom.specQuestionCount.value = spec.question_count || "";
  dom.specAnswerType.value = spec.answer_type || "";
  dom.specLanguage.value = spec.answer_language || "";

  const items = Array.isArray(spec.item_word_limits) && spec.item_word_limits.some((n) => n) ? spec.item_word_limits : null;
  State.detectedItemLimits = null;
  dom.specWordLimit.placeholder = "Tidak ada";
  if (items && items.every((n) => n === items[0])) {
    dom.specWordScope.value = "per_soal";
    dom.specWordLimit.value = items[0];
  } else if (items) {
    dom.specWordScope.value = "per_soal";
    dom.specWordLimit.value = "";
    dom.specWordLimit.placeholder = "Beda tiap soal";
    State.detectedItemLimits = items;
  } else {
    dom.specWordScope.value = "total";
    dom.specWordLimit.value = spec.word_limit || "";
  }

  State.detectedSections = Array.isArray(spec.required_sections) && spec.required_sections.length ? spec.required_sections : null;
  State.specSource = source;
  // Dosen jelas tidak butuh sitasi, jadi pencarian jurnal tidak perlu
  if (spec.needs_citations === false && State.mode === "jurnal") setMode("forum");
  UI.renderSpecNote();
  UI.renderSpecVisibility();
}

function resetAnswerSpec() {
  dom.specQuestionCount.value = "";
  dom.specAnswerType.value = "";
  dom.specLanguage.value = "";
  dom.specWordLimit.value = "";
  dom.specWordLimit.placeholder = "Tidak ada";
  dom.specWordScope.value = "total";
  State.detectedItemLimits = null;
  State.detectedSections = null;
  State.specSource = null;
  UI.renderSpecNote();
  UI.renderSpecVisibility();
}

// Kode mata kuliah UT dari lembar soal mengisi nama mata kuliah dan judul bahan bila masih kosong
async function applyDetectedCourse(code) {
  try {
    const data = await Api.utLookup(code);
    if (!data.found || !data.exact) return;
    if (!dom.courseName.value.trim()) dom.courseName.value = data.course.nama;
    if (!dom.materialTitle.value.trim()) dom.materialTitle.value = data.course.formatted_title;
    UI.renderSummaries();
  } catch (err) {
    /* katalog opsional, kegagalan tidak mengganggu alur */
  }
}

async function handleQuestionFile(file) {
  if (!file) return;
  const ext = "." + (file.name || "").split(".").pop().toLowerCase();
  if (![".pdf", ".docx", ".txt", ".png", ".jpg", ".jpeg", ".webp"].includes(ext)) {
    UI.showAlert("Format berkas soal belum didukung", "Unggah lembar soal dalam format PDF, Word .docx, TXT, atau screenshot PNG dan JPG.");
    return;
  }
  // Defensive UI: soal yang sudah diketik tidak ditimpa diam diam
  if (dom.topic.value.trim().length >= 3) {
    const ok = await UI.confirm({
      title: "Timpa soal yang sudah ada?",
      message: `Teks soal di kotak ketik akan diganti isi berkas ${file.name}. Draf lama tidak bisa dikembalikan.`,
      okLabel: "Ganti dengan berkas"
    });
    if (!ok) return;
  }

  UI.selectQuestionTab("upload");
  UI.renderUploadPanel(`Membaca ${file.name}. Soal bergambar atau hasil scan bisa butuh setengah menit.`);
  try {
    const data = await Api.uploadQuestion(file);
    if (!data.success || !data.text) throw new ApiError(data.message || "Teks dokumen tidak dapat diekstrak.", 422);
    State.questionFileName = data.filename;
    setQuestionText(formatQuestionText(data.questions || data.text));
    if (data.detected_guidelines) dom.instructions.value = data.detected_guidelines;
    applyAnswerSpec(data.answer_spec, data.answer_spec_source);
    if (data.detected_course_code) applyDetectedCourse(data.detected_course_code);
    UI.renderUploadPanel();
    UI.toast(data.detected_guidelines ? "Soal terbaca, rubrik dosen dipisahkan" : "Lembar soal berhasil dibaca");
  } catch (err) {
    UI.renderUploadPanel();
    UI.showError("Lembar soal belum terbaca", err, () => handleQuestionFile(file));
  } finally {
    checkSystemHealth();
  }
}

function requireQuestion() {
  if (dom.topic.value.trim().length >= 3) return true;
  UI.showAlert("Soal belum diisi", "Ketik soal atau unggah lembar soal dulu sebelum lanjut.");
  UI.selectQuestionTab("type");
  dom.topic.focus();
  return false;
}

// Batas kata yang keliru ditahan di sini supaya tidak dikirim diam diam sebagai tanpa batas
function requireValidSpec() {
  const { error } = computeWordLimits();
  if (!error) return true;
  UI.showAlert("Batas kata belum benar", error);
  dom.detailsSpec.open = true;
  dom.specWordLimit.focus();
  return false;
}

function submitTask() {
  if (!requireQuestion() || !requireValidSpec()) return;
  if (State.mode === "forum") {
    generate();
    return;
  }
  goStep(2);
  if (State.mode === "jurnal") {
    const query = dom.topic.value.trim();
    if (query !== State.lastQuery || !State.papers.length) {
      dom.refineQuery.value = query.split(/\s+/).slice(0, 12).join(" ");
      performSearch(query);
    }
  }
}

// ---------- Jurnal ----------
async function performSearch(rawQuery) {
  const query = (rawQuery || "").trim();
  if (query.length < 3) {
    UI.showAlert("Kata kunci terlalu pendek", "Ketik minimal tiga huruf untuk mencari jurnal.");
    return;
  }
  UI.clearAlert();
  State.lastQuery = dom.topic.value.trim();
  State.selectedPaperIds.clear();
  UI.renderSelection();
  UI.renderPapersLoading(true);
  dom.searchInfo.textContent = "";
  setBusy(dom.btnRefine, true, "Mencari");
  try {
    const data = await Api.search(query, 6);
    State.papers = data.papers || [];
    dom.searchInfo.textContent = data.message || "";
    if (data.query_used) dom.refineQuery.value = data.query_used;
    if (State.papers.length) UI.renderPapers();
    else UI.renderPapersEmpty(data.message, data.query_used || query);
  } catch (err) {
    State.papers = [];
    dom.papersList.replaceChildren();
    UI.showError("Pencarian jurnal gagal", err, () => performSearch(query));
  } finally {
    UI.renderPapersLoading(false);
    setBusy(dom.btnRefine, false);
  }
}

function togglePaper(id, checked) {
  if (checked) State.selectedPaperIds.add(id);
  else State.selectedPaperIds.delete(id);
  UI.renderSelection();
}

async function addManualPaper() {
  const value = dom.manualDoi.value.trim();
  if (value.length < 3) return dom.manualDoi.focus();
  setBusy(dom.btnAddManual, true, "Mencari");
  try {
    const data = await Api.search(value, 1);
    const paper = data.papers && data.papers[0];
    if (!paper) {
      UI.showAlert("Naskah tidak ditemukan", "DOI atau judul itu tidak ada di registri ilmiah. Pastikan format DOI seperti 10.xxxx/...");
      return;
    }
    if (!State.papers.some((p) => p.id === paper.id)) State.papers.unshift(paper);
    State.selectedPaperIds.add(paper.id);
    dom.manualDoi.value = "";
    dom.manualForm.classList.add("hidden");
    dom.btnToggleManual.setAttribute("aria-expanded", "false");
    UI.renderPapers();
    UI.renderSelection();
    UI.toast("Naskah ditambahkan dan dicentang");
  } catch (err) {
    UI.showError("Gagal menambahkan naskah", err, addManualPaper);
  } finally {
    setBusy(dom.btnAddManual, false);
  }
}

// ---------- Bahan dosen ----------
async function handleMaterialFile(file) {
  if (!file) return;
  const ext = "." + (file.name || "").split(".").pop().toLowerCase();
  if (![".pdf", ".docx", ".txt", ".md"].includes(ext)) {
    UI.showAlert("Format bahan belum didukung", "Unggah bahan dalam format PDF, Word .docx, TXT, atau MD.");
    return;
  }
  if (file.size > 20 * 1024 * 1024) {
    UI.showAlert("Berkas terlalu besar", "Batasnya 20 MB. Pecah dulu per bab lalu unggah satu per satu.");
    return;
  }
  if (dom.materialText.value.trim().length >= 15) {
    const ok = await UI.confirm({
      title: "Ganti isi naskah?",
      message: `Teks di kotak isi naskah akan diganti isi ${file.name}. Simpan dulu bahan sebelumnya jika masih dipakai.`,
      okLabel: "Ganti isi"
    });
    if (!ok) return;
  }

  dom.materialDropzone.classList.add("hidden");
  dom.materialReading.classList.remove("hidden");
  dom.materialReadingText.textContent = `Membaca ${file.name} secara lokal`;
  try {
    const data = await Api.parseReadingDoc(file);
    if (!data.success) throw new ApiError(data.message, 422);
    dom.materialText.value = data.text;
    // Baris 'by Willa Cather' di awal naskah lebih bisa dipercaya daripada nama berkas yang sering mencampur judul dan penulis
    const byline = findByline(data.text);
    if (!dom.materialAuthor.value.trim() && byline) dom.materialAuthor.value = byline.author;
    if (!dom.materialTitle.value.trim()) {
      dom.materialTitle.value = (byline && byline.title) || file.name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ");
    }
    UI.renderMaterialPreview();
    UI.toast(`${formatNumber(data.char_count)} karakter terbaca`);
  } catch (err) {
    UI.showError("Bahan bacaan belum terbaca", err, () => handleMaterialFile(file));
  } finally {
    dom.materialReading.classList.add("hidden");
    dom.materialDropzone.classList.remove("hidden");
    checkSystemHealth();
  }
}

function materialFormFilled() {
  return dom.materialText.value.trim().length >= 15;
}

function readMaterialForm() {
  const year = readInt(dom.materialYear);
  return {
    module_title: dom.materialTitle.value.trim(),
    author: dom.materialAuthor.value.trim() || null,
    year: year && year >= 1000 && year <= 2100 ? year : null,
    publisher_or_venue: dom.materialPublisher.value.trim() || null,
    page_or_ref: dom.materialPage.value.trim() || null,
    content_text: dom.materialText.value.trim()
  };
}

function clearMaterialForm() {
  [dom.materialTitle, dom.materialAuthor, dom.materialYear, dom.materialPublisher, dom.materialPage, dom.materialText].forEach((input) => { input.value = ""; });
  dom.publicationResult.classList.add("hidden");
  UI.renderUtResult(null);
  UI.renderMaterialPreview();
}

// Mengembalikan true jika bahan berhasil tersimpan
async function saveMaterial() {
  const payload = readMaterialForm();
  if (payload.module_title.length < 3) {
    UI.showAlert("Judul naskah belum diisi", "Isi judul naskah minimal tiga huruf, misalnya judul cerpen atau kode mata kuliah UT.");
    dom.materialTitle.focus();
    return false;
  }
  if (payload.content_text.length < 15) {
    UI.showAlert("Isi naskah masih kosong", "Unggah berkas bahan atau tempel minimal beberapa kalimat materi.");
    dom.materialText.focus();
    return false;
  }
  setBusy(dom.btnSaveMaterial, true, "Menyimpan");
  try {
    const material = await Api.saveMaterial(payload);
    State.materials.push(material);
    clearMaterialForm();
    UI.renderMaterialList();
    UI.renderSelection();
    UI.toast("Bahan tersimpan sebagai rujukan");
    return true;
  } catch (err) {
    UI.showError("Bahan belum tersimpan", err, saveMaterial);
    return false;
  } finally {
    setBusy(dom.btnSaveMaterial, false);
  }
}

function removeMaterial(id) {
  State.materials = State.materials.filter((m) => m.id !== id);
  UI.renderMaterialList();
  UI.renderSelection();
  renderSavedModulesCards();
}

async function loadAndRenderSavedModules(forceToast = false) {
  if (!dom.panelSavedLibrary || !dom.savedModulesContainer) return;
  try {
    const res = await Api.getSavedModules();
    State.savedModules = (res && res.modules) || [];
    if (!State.savedModules.length) {
      dom.panelSavedLibrary.classList.add("hidden");
      return;
    }
    dom.panelSavedLibrary.classList.remove("hidden");
    dom.savedLibraryCount.textContent = `${State.savedModules.length} modul`;
    renderSavedModulesCards();
    if (forceToast) UI.toast(`${State.savedModules.length} modul siap di pustaka`);
  } catch (err) {
    console.warn("Gagal memuat pustaka modul tersimpan:", err);
  }
}

function renderSavedModulesCards() {
  if (!dom.savedModulesContainer) return;
  dom.savedModulesContainer.replaceChildren(...State.savedModules.map((m) => {
    const isLoaded = State.materials.some((mat) => mat.id === m.id || mat.title === m.title);
    const card = el("div", `p-4 rounded-2xl border transition-colors ${isLoaded ? "border-ok-line bg-ok-bg/30" : "border-line bg-subtle"}`);

    const topRow = el("div", "flex items-start justify-between gap-3");
    const info = el("div", "flex-1 min-w-0");
    info.append(el("h3", `text-xs font-bold leading-snug ${isLoaded ? "text-ok-text" : "text-ink"}`, m.title));

    const metaParts = [(m.authors || []).join(", "), m.year, m.venue].filter(Boolean);
    if (metaParts.length) {
      info.append(el("p", "text-[11px] text-ink-3 mt-0.5 truncate", metaParts.join(" · ")));
    }

    const stats = el("p", "text-[11px] font-mono text-ink-2 mt-1", `${m.chunk_count} bagian · ${formatNumber(m.char_count)} karakter`);
    info.append(stats);

    if (m.abstract) {
      info.append(el("p", "text-[11px] text-ink-3 line-clamp-2 mt-1.5 leading-relaxed", m.abstract));
    }

    const btnWrapper = el("div", "shrink-0 pt-0.5");
    const btn = el("button", `btn text-xs px-3 py-1.5 ${isLoaded ? "btn-secondary opacity-75" : "btn-primary"}`);
    btn.type = "button";
    if (isLoaded) {
      btn.innerHTML = `${ICON.check} Digunakan`;
      btn.disabled = true;
    } else {
      btn.textContent = "Gunakan Modul";
      btn.addEventListener("click", () => handleLoadSavedModule(m, btn));
    }
    btnWrapper.append(btn);

    topRow.append(info, btnWrapper);
    card.append(topRow);
    return card;
  }));
}

async function handleLoadSavedModule(m, btn) {
  setBusy(btn, true, "Memuat");
  try {
    const loaded = await Api.loadSavedModule(m.id || m.filename);
    if (!State.materials.some((x) => x.id === loaded.id)) {
      State.materials.push(loaded);
    }
    if (!dom.courseName.value.trim()) {
      const match = (loaded.title || "").match(/^[A-Z]{4}\d{4}/);
      if (match) applyDetectedCourse(match[0]);
    }
    UI.renderMaterialList();
    UI.renderSelection();
    renderSavedModulesCards();
    UI.toast(`Modul ${loaded.title} siap digunakan`);
  } catch (err) {
    UI.showError("Gagal memuat modul tersimpan", err, () => handleLoadSavedModule(m, btn));
  } finally {
    setBusy(btn, false);
  }
}

async function saveToPermanentLibrary() {
  const payload = readMaterialForm();
  if (payload.module_title.length < 3) {
    UI.showAlert("Judul naskah belum diisi", "Isi judul naskah minimal tiga huruf sebelum menyimpan ke folder modul.");
    dom.materialTitle.focus();
    return;
  }
  if (payload.content_text.length < 15) {
    UI.showAlert("Isi naskah masih kosong", "Unggah berkas bahan atau tempel isi naskah minimal 15 karakter.");
    dom.materialText.focus();
    return;
  }
  setBusy(dom.btnSaveToLibrary, true, "Menyimpan ke pustaka");
  try {
    const saved = await Api.saveSavedModule(payload);
    if (!State.materials.some((x) => x.id === saved.id)) {
      State.materials.push(saved);
    }
    clearMaterialForm();
    UI.renderMaterialList();
    UI.renderSelection();
    await loadAndRenderSavedModules();
    UI.toast(`Modul ${saved.title} tersimpan permanen di folder saved_modules`);
  } catch (err) {
    UI.showError("Gagal menyimpan ke pustaka modul", err, saveToPermanentLibrary);
  } finally {
    setBusy(dom.btnSaveToLibrary, false);
  }
}

function attachUtLookup() {
  let timer = null;
  let lastQuery = "";
  const apply = (course) => {
    dom.materialTitle.value = course.formatted_title;
    if (!dom.materialAuthor.value.trim()) dom.materialAuthor.value = "Universitas Terbuka";
    if (!dom.courseName.value.trim()) dom.courseName.value = course.nama;
    UI.renderUtResult(null);
    UI.renderSummaries();
  };
  const lookup = async () => {
    const query = dom.materialTitle.value.trim();
    // Hanya pola yang mirip kode mata kuliah, supaya judul cerpen biasa tidak memicu saran UT
    if (!/[A-Za-z]{3,4}\s*-?\s*\d{2,4}/.test(query)) return UI.renderUtResult(null);
    if (query === lastQuery) return;
    lastQuery = query;
    dom.materialUtSpinner.classList.remove("hidden");
    try {
      const data = await Api.utLookup(query);
      const useful = data.found && data.course && (data.exact || (data.suggestions || []).length);
      UI.renderUtResult(useful ? data : null, apply);
    } catch (err) {
      UI.renderUtResult(null);
    } finally {
      dom.materialUtSpinner.classList.add("hidden");
    }
  };
  dom.materialTitle.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(lookup, 250);
  });
}

async function readScreenshot(file) {
  if (!file || !file.type.startsWith("image/")) {
    UI.showAlert("Berkas bukan gambar", "Pilih tangkapan layar berformat PNG, JPG, atau WebP.");
    return;
  }
  dom.materialOcrStatus.classList.remove("hidden");
  try {
    const dataUrl = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
    const data = await Api.extractScreenshot(dataUrl);
    if (!data.success || !data.extracted_text) throw new ApiError(data.message || "Teks pada gambar tidak terbaca jelas.", 422);
    const current = dom.materialText.value.trim();
    dom.materialText.value = current ? `${current}\n\n${data.extracted_text}` : data.extracted_text;
    UI.renderMaterialPreview();
    UI.toast(`${formatNumber(data.extracted_text.length)} karakter dari gambar ditambahkan`);
  } catch (err) {
    UI.showError("Gambar belum terbaca", err, () => readScreenshot(file));
  } finally {
    dom.materialOcrStatus.classList.add("hidden");
    checkSystemHealth();
  }
}

// ---------- Generate ----------
let pipelineTimers = [];
function runPipelineAnimation() {
  pipelineTimers.forEach(clearTimeout);
  UI.renderPipeline(1);
  pipelineTimers = [[2, 1500], [3, 4000], [4, 14000]].map(([n, ms]) => setTimeout(() => UI.renderPipeline(n), ms));
}

async function collectPaperIds() {
  if (State.mode === "forum") return [];
  if (State.mode === "jurnal") return Array.from(State.selectedPaperIds);
  // Bahan yang masih di formulir ikut disimpan supaya tidak hilang
  if (materialFormFilled() && !(await saveMaterial())) return null;
  if (!State.materials.length) {
    UI.showAlert("Belum ada bahan bacaan", "Unggah atau tempel naskah dari dosen dulu, lalu tulis naskahnya.");
    return null;
  }
  return State.materials.map((m) => m.id);
}

async function generate() {
  if (State.generating) return;
  if (!requireQuestion() || !requireValidSpec()) return;
  const paperIds = await collectPaperIds();
  if (!paperIds) return;

  const returnStep = State.mode === "forum" ? 1 : 2;
  State.generating = true;
  goStep(3);
  UI.renderGenerating(true);
  runPipelineAnimation();
  try {
    const data = await Api.generate(buildGeneratePayload(paperIds));
    if (!data.success) throw new ApiError("Naskah gagal disusun. Coba sekali lagi.", 500);
    State.taskId = data.task_id;
    State.doc = {
      title: data.title,
      sections: data.sections,
      references: data.references,
      identityLines: data.identity_lines || [],
      wordCount: data.word_count,
      language: data.language
    };
    State.sectionHistory = {};
    UI.renderPipeline(5);
    UI.renderEvidence(data.evidence);
    UI.renderDocument();
    UI.renderGenerating(false);
    UI.toast("Naskah selesai disusun");
  } catch (err) {
    UI.renderGenerating(false);
    // Naskah lama tetap valid di server, jadi kegagalan tulis ulang tidak membuang Tahap 3
    if (!State.doc) {
      State.maxStep = returnStep;
      goStep(returnStep);
    }
    if (err instanceof ApiError && err.isRateLimited) {
      UI.showAlert("Gemini sedang jeda", `${err.message} Tunggu lampu status di pojok kanan atas kembali hijau, lalu coba lagi.`, { retry: generate });
    } else {
      UI.showError("Naskah belum berhasil disusun", err, generate);
    }
  } finally {
    pipelineTimers.forEach(clearTimeout);
    State.generating = false;
    checkSystemHealth();
  }
}

// ---------- Studio naskah ----------
// Simpan versi lama satu bagian sebelum diganti. Dibatasi supaya memori tidak membengkak.
function rememberSection(index, section) {
  const history = State.sectionHistory[index] || (State.sectionHistory[index] = []);
  history.push({ heading: section.heading, content: section.content });
  if (history.length > 10) history.shift();
}

async function saveDocument(doc, container, changedIndex = null) {
  UI.setDocBusy(true);
  try {
    const previous = changedIndex === null ? null : State.doc.sections[changedIndex];
    const data = await Api.updateTask(State.taskId, doc);
    if (previous) rememberSection(changedIndex, previous);
    Object.assign(State.doc, { title: data.title, sections: data.sections, wordCount: data.word_count });
    UI.setDocBusy(false);
    UI.renderDocument();
    UI.toast("Perubahan tersimpan");
  } catch (err) {
    UI.setDocBusy(false);
    UI.showSectionError(container, `Gagal menyimpan: ${err.message}`);
  }
}

async function rewriteSection(article, index, instruction) {
  const body = article.querySelector(".section-body");
  const original = State.doc.sections[index].content;
  body.replaceChildren(...[100, 92, 96, 70].map((w) => {
    const bar = el("div", "doc-skeleton");
    bar.style.width = `${w}%`;
    return bar;
  }));
  const status = el("p", "doc-error !text-stone-500", "Gemini sedang menulis ulang bagian ini");
  status.setAttribute("role", "status");
  body.append(status);
  UI.setDocBusy(true);
  try {
    const previous = State.doc.sections[index];
    const data = await Api.rewriteSection(State.taskId, index, instruction);
    rememberSection(index, previous);
    Object.assign(State.doc, { title: data.title, sections: data.sections, wordCount: data.word_count });
    UI.setDocBusy(false);
    UI.renderDocument();
    UI.toast("Bagian ditulis ulang. Tekan Kembalikan jika versi lama lebih baik");
  } catch (err) {
    UI.setDocBusy(false);
    UI.fillParagraphs(body, original);
    UI.showSectionError(article, err.message || "Gagal menghubungi server.");
  } finally {
    checkSystemHealth();
  }
}

// Mengembalikan satu bagian ke versi sebelum diedit atau ditulis ulang, lalu menyimpan ulang berkas Word dan PDF
async function restoreSection(article, index) {
  const history = State.sectionHistory[index];
  if (!history || !history.length) return;
  const previous = history[history.length - 1];
  const sections = State.doc.sections.map((s, i) => i === index ? previous : s);
  UI.setDocBusy(true);
  try {
    const data = await Api.updateTask(State.taskId, { title: State.doc.title, sections });
    history.pop();
    Object.assign(State.doc, { title: data.title, sections: data.sections, wordCount: data.word_count });
    UI.setDocBusy(false);
    UI.renderDocument();
    UI.toast("Versi sebelumnya dikembalikan");
  } catch (err) {
    UI.setDocBusy(false);
    UI.showSectionError(article, `Gagal mengembalikan: ${err.message}`);
  }
}

async function copyDocument() {
  if (!State.doc) return;
  const text = documentAsText();
  try {
    await navigator.clipboard.writeText(text);
  } catch (err) {
    // Cadangan untuk webview yang menolak Clipboard API
    const area = el("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.append(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  }
  UI.toast("Naskah berhasil disalin");
}

function download(type) {
  if (State.taskId) window.location.href = `/api/download/${type}/${State.taskId}`;
}

async function regenerateAll() {
  const ok = await UI.confirm({
    title: "Tulis ulang seluruh naskah?",
    message: "Semua isi naskah, termasuk editan kamu, diganti tulisan baru dengan soal dan rujukan yang sama.",
    okLabel: "Tulis ulang"
  });
  if (ok) generate();
}

async function startNewTask() {
  const ok = await UI.confirm({
    title: "Mulai tugas baru?",
    message: "Soal, rujukan, dan naskah ini dibersihkan dari layar. Berkas yang sudah diunduh tetap aman di laptop. Nama dan NIM tetap diingat.",
    okLabel: "Mulai baru"
  });
  if (!ok) return;
  State.questionFileName = "";
  setQuestionText("");
  storage.remove(STORAGE.draft);
  storage.remove(STORAGE.draftSetup);
  dom.draftStatus.textContent = "";
  dom.instructions.value = "";
  dom.courseName.value = "";
  resetAnswerSpec();
  State.papers = [];
  State.selectedPaperIds.clear();
  State.lastQuery = "";
  State.materials = [];
  State.taskId = null;
  State.doc = null;
  State.sectionHistory = {};
  dom.papersList.replaceChildren();
  dom.searchInfo.textContent = "";
  clearMaterialForm();
  UI.selectQuestionTab("type");
  State.maxStep = 1;
  goStep(1);
}

// ---------- Tema dan jendela desktop ----------
function syncDesktopTitlebar(isDark) {
  if (window.pywebview && window.pywebview.api) window.pywebview.api.set_titlebar(isDark);
}

function applyTheme(isDark) {
  document.documentElement.classList.toggle("dark", isDark);
  document.documentElement.setAttribute("data-theme", isDark ? "dark" : "light");
  syncDesktopTitlebar(isDark);
}

function setMaximizedIcon(isMaximized) {
  $("icon-window-maximize").classList.toggle("hidden", isMaximized);
  $("icon-window-restore").classList.toggle("hidden", !isMaximized);
  const btn = $("btn-window-maximize");
  btn.setAttribute("aria-label", isMaximized ? "Kembalikan ukuran jendela" : "Besarkan jendela");
  btn.title = isMaximized ? "Kembalikan" : "Besarkan";
}

async function toggleMaximize() {
  setMaximizedIcon(await window.pywebview.api.toggle_maximize());
}

// Jendela desktop tanpa bingkai: header aplikasi jadi title bar, tombol jendela dipasang di ujung kanan
function enableDesktopChrome() {
  const api = window.pywebview.api;
  const inner = $("app-header-inner");
  inner.classList.remove("max-w-6xl", "mx-auto", "pr-5");
  inner.classList.add("pr-0");
  $("window-controls").classList.replace("hidden", "flex");
  document.querySelectorAll(".desktop-drag").forEach((node) => {
    node.classList.add("pywebview-drag-region");
    node.addEventListener("dblclick", toggleMaximize);
  });
  $("btn-window-minimize").addEventListener("click", () => api.minimize());
  $("btn-window-maximize").addEventListener("click", toggleMaximize);
  $("btn-window-close").addEventListener("click", () => api.close());
}

// =====================================================================
// 6. EVENT WIRING
// =====================================================================
function bindDropzone(zone, input, onFile) {
  zone.addEventListener("click", () => input.click());
  input.addEventListener("change", () => {
    if (input.files && input.files[0]) onFile(input.files[0]);
    input.value = "";
  });
  ["dragenter", "dragover"].forEach((name) => zone.addEventListener(name, (e) => {
    e.preventDefault();
    zone.classList.add("is-dragover");
  }));
  ["dragleave", "drop"].forEach((name) => zone.addEventListener(name, (e) => {
    e.preventDefault();
    zone.classList.remove("is-dragover");
  }));
  zone.addEventListener("drop", (e) => {
    const file = e.dataTransfer && e.dataTransfer.files[0];
    if (file) onFile(file);
  });
}

function init() {
  // Tema
  const savedTheme = storage.get(STORAGE.theme);
  const prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  applyTheme(savedTheme ? savedTheme === "dark" : prefersDark);
  $("btn-toggle-theme").addEventListener("click", () => {
    const next = !document.documentElement.classList.contains("dark");
    applyTheme(next);
    storage.set(STORAGE.theme, next ? "dark" : "light");
  });

  // Identitas dan gaya bahasa diingat antar sesi. Mata kuliah beda tiap tugas jadi tidak disimpan.
  dom.studentName.value = storage.get(STORAGE.name);
  dom.studentId.value = storage.get(STORAGE.nim);
  [[dom.studentName, STORAGE.name], [dom.studentId, STORAGE.nim]].forEach(([input, key]) => {
    input.addEventListener("input", () => {
      storage.set(key, input.value.trim());
      UI.renderSummaries();
    });
  });
  dom.courseName.addEventListener("input", UI.renderSummaries);
  if (!setRadio("tone", storage.get(STORAGE.tone))) setRadio("tone", "akademis formal");
  // Pilihan sitasi kutipan diingat, karena biasanya sama untuk semua tugas dari dosen yang sama
  dom.quoteCitations.checked = storage.get(STORAGE.quoteCitations) === "1";
  dom.quoteCitations.addEventListener("change", () => storage.set(STORAGE.quoteCitations, dom.quoteCitations.checked ? "1" : "0"));
  document.querySelectorAll('input[name="tone"]').forEach((input) => input.addEventListener("change", () => {
    storage.set(STORAGE.tone, input.value);
    UI.renderSummaries();
  }));

  // Jalur
  setMode(storage.get(STORAGE.mode) || "jurnal");
  document.querySelectorAll('input[name="mode"]').forEach((input) => input.addEventListener("change", () => setMode(input.value)));

  // Soal: draf dipulihkan dari sesi sebelumnya
  const draft = storage.get(STORAGE.draft);
  if (draft) {
    dom.topic.value = draft;
    dom.draftStatus.textContent = "Draf dari sesi sebelumnya dipulihkan";
  }
  try {
    const setup = JSON.parse(storage.get(STORAGE.draftSetup) || "null");
    if (setup) {
      dom.instructions.value = setup.instructions || "";
      if (setup.source) applyAnswerSpec(setup.spec, setup.source);
    }
  } catch (err) { /* draf rusak diabaikan, pengguna tinggal isi ulang */ }
  UI.renderTopicMeta();
  dom.topic.addEventListener("input", () => {
    UI.renderTopicMeta();
    saveDraft();
  });
  [dom.instructions, dom.specQuestionCount, dom.specAnswerType, dom.specLanguage, dom.specWordLimit, dom.specWordScope]
    .forEach((input) => input.addEventListener("input", saveDraft));

  // Tab soal dengan navigasi panah kiri kanan
  dom.tabType.addEventListener("click", () => UI.selectQuestionTab("type"));
  dom.tabUpload.addEventListener("click", () => UI.selectQuestionTab("upload"));
  [dom.tabType, dom.tabUpload].forEach((tab) => tab.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    const next = tab === dom.tabType ? dom.tabUpload : dom.tabType;
    UI.selectQuestionTab(next === dom.tabUpload ? "upload" : "type");
    next.focus();
  }));
  bindDropzone(dom.questionDropzone, dom.questionFile, handleQuestionFile);
  $("btn-replace-question-file").addEventListener("click", () => dom.questionFile.click());
  $("btn-edit-question-text").addEventListener("click", () => {
    UI.selectQuestionTab("type");
    dom.topic.focus();
  });

  // Setelan jawaban
  dom.specWordLimit.addEventListener("input", () => {
    // Angka yang diketik menggantikan batas berbeda per soal hasil deteksi
    if (dom.specWordLimit.value) State.detectedItemLimits = null;
    UI.renderSpecVisibility();
  });
  [dom.specWordScope, dom.specAnswerType, dom.selectLength].forEach((node) => node.addEventListener("change", UI.renderSpecVisibility));
  dom.specQuestionCount.addEventListener("input", UI.renderSpecVisibility);
  UI.renderSpecNote();
  UI.renderSpecVisibility();

  dom.formTask.addEventListener("submit", (e) => {
    e.preventDefault();
    submitTask();
  });

  // Tahap 2
  $("btn-back-step-1").addEventListener("click", () => goStep(1));
  dom.refineForm.addEventListener("submit", (e) => {
    e.preventDefault();
    performSearch(dom.refineQuery.value);
  });
  dom.btnToggleManual.addEventListener("click", () => {
    const open = dom.manualForm.classList.toggle("hidden") === false;
    dom.btnToggleManual.setAttribute("aria-expanded", String(open));
    if (open) dom.manualDoi.focus();
  });
  dom.manualForm.addEventListener("submit", (e) => {
    e.preventDefault();
    addManualPaper();
  });

  bindDropzone(dom.materialDropzone, dom.materialFile, handleMaterialFile);
  let previewTimer = null;
  dom.materialText.addEventListener("input", () => {
    UI.renderMaterialMeta();
    clearTimeout(previewTimer);
    previewTimer = setTimeout(UI.renderMaterialPreview, 300);
  });
  $("btn-pick-material-screenshot").addEventListener("click", () => dom.materialScreenshot.click());
  dom.materialScreenshot.addEventListener("change", () => {
    if (dom.materialScreenshot.files[0]) readScreenshot(dom.materialScreenshot.files[0]);
    dom.materialScreenshot.value = "";
  });
  dom.btnSaveMaterial.addEventListener("click", saveMaterial);
  if (dom.btnSaveToLibrary) dom.btnSaveToLibrary.addEventListener("click", saveToPermanentLibrary);
  if (dom.btnRefreshSavedLibrary) dom.btnRefreshSavedLibrary.addEventListener("click", () => loadAndRenderSavedModules(true));
  dom.btnLookupPublication.addEventListener("click", lookupPublicationInfo);
  attachUtLookup();
  dom.btnGenerate.addEventListener("click", generate);

  // Ctrl+V gambar dari Snipping Tool: di Tahap 1 jadi lembar soal, di Tahap 2 jadi bahan dosen
  window.addEventListener("paste", (e) => {
    const onQuestion = State.step === 1;
    if (!onQuestion && (State.step !== 2 || State.mode !== "bahan")) return;
    // Salinan dari Word juga membawa versi gambar. Kalau ada teksnya, biarkan jadi tempel teks biasa.
    if (e.clipboardData && e.clipboardData.types.includes("text/plain")) return;
    const item = Array.from((e.clipboardData && e.clipboardData.items) || []).find((i) => i.type.startsWith("image/"));
    const file = item && item.getAsFile();
    if (!file) return;
    e.preventDefault();
    if (onQuestion) {
      // Gambar tempelan tidak punya nama berkas, jadi diberi nama supaya ekstensinya terbaca
      const ext = (file.type.split("/")[1] || "png").replace("jpeg", "jpg");
      handleQuestionFile(new File([file], `soal-tempel.${ext}`, { type: file.type }));
    } else {
      readScreenshot(file);
    }
  });

  // Tahap 3
  $("btn-download-docx").addEventListener("click", () => download("docx"));
  $("btn-download-pdf").addEventListener("click", () => download("pdf"));
  $("btn-copy-text").addEventListener("click", copyDocument);
  dom.btnRegenerate.addEventListener("click", regenerateAll);
  $("btn-new-task").addEventListener("click", startNewTask);

  // Di mode desktop, API pywebview baru siap setelah halaman dimuat
  window.addEventListener("pywebviewready", () => {
    enableDesktopChrome();
    syncDesktopTitlebar(document.documentElement.classList.contains("dark"));
    window.pywebview.api.fit_height(document.documentElement.scrollHeight);
  });

  UI.showStep(1);
  checkSystemHealth();
}

init();
