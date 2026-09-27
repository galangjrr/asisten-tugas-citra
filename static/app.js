let currentPapers = [];
let selectedPaperIds = new Set();
let currentTaskId = null;
let progressInterval = null;
let pendingManualModule = null;


// DOM Elements
const apiStatusBadge = document.getElementById("api-status-badge");
const globalAlert = document.getElementById("global-alert");
const formSearch = document.getElementById("form-search");
const inputTopic = document.getElementById("input-topic");
const selectFormat = document.getElementById("select-format");
const selectLength = document.getElementById("select-length");
const customWordsWrapper = document.getElementById("custom-words-wrapper");
const inputCustomWords = document.getElementById("input-custom-words");
const selectDepth = document.getElementById("select-depth");
const selectTone = document.getElementById("select-tone");
const inputInstructions = document.getElementById("input-instructions");
const btnSearch = document.getElementById("btn-search");

// Question File Upload Elements
const btnUploadQuestionFile = document.getElementById("btn-upload-question-file");
const uploadQuestionFile = document.getElementById("upload-question-file");
const questionFileStatus = document.getElementById("question-file-status");
const questionFileStatusText = document.getElementById("question-file-status-text");
const questionFileBadge = document.getElementById("question-file-badge");
const questionFileInfo = document.getElementById("question-file-info");
const btnClearQuestionFile = document.getElementById("btn-clear-question-file");

async function handleQuestionFileUpload(file) {
  if (!file) return;

  const validExts = [".pdf", ".docx", ".txt"];
  const fileName = file.name || "dokumen_soal";
  const ext = "." + fileName.split(".").pop().toLowerCase();
  if (!validExts.includes(ext)) {
    showAlert("Format Berkas Tidak Didukung", "Silakan unggah lembar soal dalam format PDF, Word (.docx), atau berkas teks (.txt).");
    return;
  }

  if (questionFileStatus) {
    questionFileStatus.classList.remove("hidden");
    if (questionFileStatusText) questionFileStatusText.textContent = `Mengekstrak teks soal dari ${fileName}...`;
  }

  try {
    const formData = new FormData();
    formData.append("file", file);

    const res = await fetch("/api/upload-question-file", {
      method: "POST",
      body: formData
    });

    const data = await res.json();
    if (questionFileStatus) questionFileStatus.classList.add("hidden");

    if (data.success && data.text) {
      if (inputTopic) {
        inputTopic.value = data.questions || data.text;
      }

      if (data.detected_guidelines && inputInstructions) {
        inputInstructions.value = data.detected_guidelines;
      }

      if (data.word_count_hint && selectLength) {
        if (data.word_count_hint <= 600) {
          selectLength.value = "ringkas";
        } else if (data.word_count_hint <= 1200) {
          selectLength.value = "sedang";
        } else {
          selectLength.value = "panjang";
        }
        selectLength.dispatchEvent(new Event("change"));
      }

      if (questionFileInfo) {
        if (data.detected_guidelines) {
          questionFileInfo.textContent = `Memuat "${data.filename}" (${data.char_count} karakter). Pertanyaan inti tugas dan kriteria petunjuk dosen berhasil dipisahkan otomatis.`;
        } else {
          questionFileInfo.textContent = `Memuat "${data.filename}" (${data.char_count} karakter). Seluruh lembar soal tersimpan utuh dan bebas dari distorsi penulisan.`;
        }
      }

      if (questionFileBadge) questionFileBadge.classList.remove("hidden");

      // Deteksi otomatis kode mata kuliah UT dari lembar soal jika ada
      if (data.detected_course_code && inputStep1UtCode) {
        if (!inputStep1UtCode.value) {
          inputStep1UtCode.value = data.detected_course_code;
          inputStep1UtCode.dispatchEvent(new Event("input"));
        }
      }

      showAlert(
        "Lembar Soal Berhasil Dimuat",
        `Teks dari "${data.filename}" berhasil dimuat ke kotak tugas secara utuh tanpa ada yang terpotong.`,
        "",
        "success"
      );
    } else {
      showAlert(
        "Gagal Membaca Berkas Soal",
        data.message || "Teks dokumen tidak dapat diekstrak.",
        "Pastikan berkas PDF atau Word tidak terkunci atau rusak."
      );
    }
  } catch (err) {
    if (questionFileStatus) questionFileStatus.classList.add("hidden");
    showAlert("Gagal Menghubungi Server", "Periksa koneksi server lokal.");
  }
}

if (btnUploadQuestionFile && uploadQuestionFile) {
  btnUploadQuestionFile.addEventListener("click", () => {
    uploadQuestionFile.click();
  });
  uploadQuestionFile.addEventListener("change", (e) => {
    if (e.target.files && e.target.files[0]) {
      handleQuestionFileUpload(e.target.files[0]);
      e.target.value = "";
    }
  });
}

if (btnClearQuestionFile) {
  btnClearQuestionFile.addEventListener("click", () => {
    if (inputTopic) inputTopic.value = "";
    if (questionFileBadge) questionFileBadge.classList.add("hidden");
    if (uploadQuestionFile) uploadQuestionFile.value = "";
  });
}

if (inputTopic) {
  ["dragenter", "dragover"].forEach((evtName) => {
    inputTopic.addEventListener(evtName, (e) => {
      e.preventDefault();
      e.stopPropagation();
      inputTopic.classList.add("ring-2", "ring-stone-900", "bg-stone-50");
    });
  });

  ["dragleave", "drop"].forEach((evtName) => {
    inputTopic.addEventListener(evtName, (e) => {
      e.preventDefault();
      e.stopPropagation();
      inputTopic.classList.remove("ring-2", "ring-stone-900", "bg-stone-50");
    });
  });

  inputTopic.addEventListener("drop", (e) => {
    if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleQuestionFileUpload(e.dataTransfer.files[0]);
    }
  });
}

if (selectLength && customWordsWrapper) {
  selectLength.addEventListener("change", () => {
    if (selectLength.value === "kustom") {
      customWordsWrapper.classList.remove("hidden");
    } else {
      customWordsWrapper.classList.add("hidden");
    }
  });
}

const step1 = document.getElementById("step-1");
const step2 = document.getElementById("step-2");
const step3 = document.getElementById("step-3");
const stepTab1 = document.getElementById("step-tab-1");
const stepTab2 = document.getElementById("step-tab-2");
const stepTab3 = document.getElementById("step-tab-3");

const searchBackendInfo = document.getElementById("search-backend-info");
const papersLoading = document.getElementById("papers-loading");
const papersList = document.getElementById("papers-list");
const generateActions = document.getElementById("generate-actions");
const selectedCountLabel = document.getElementById("selected-count-label");
const btnGenerate = document.getElementById("btn-generate");
const btnBackStep1 = document.getElementById("btn-back-step-1");

const generatingIndicator = document.getElementById("generating-indicator");
const genStepTitle = document.getElementById("gen-step-title");
const genStepDesc = document.getElementById("gen-step-desc");
const logStep1 = document.getElementById("log-step-1");
const logStep2 = document.getElementById("log-step-2");
const logStep3 = document.getElementById("log-step-3");
const logStep4 = document.getElementById("log-step-4");

const resultContainer = document.getElementById("result-container");
const resultTitle = document.getElementById("result-title");
const resultStats = document.getElementById("result-stats");
const previewContent = document.getElementById("preview-content");
const btnDownloadDocx = document.getElementById("btn-download-docx");
const btnDownloadPdf = document.getElementById("btn-download-pdf");
const btnRestart = document.getElementById("btn-restart");

function showAlert(title, message, advice = "", type = "error") {
  const isErr = type === "error";
  globalAlert.className = `mb-6 p-4 sm:p-5 rounded-2xl border text-sm ${
    isErr 
      ? "bg-rose-50 dark:bg-rose-950/40 border-rose-200 dark:border-rose-900/60 text-rose-900 dark:text-rose-200" 
      : "bg-emerald-50 dark:bg-emerald-950/40 border-emerald-200 dark:border-emerald-900/60 text-emerald-900 dark:text-emerald-200"
  }`;
  
  globalAlert.innerHTML = `
    <div class="flex items-start space-x-3">
      <div class="w-5 h-5 rounded-full ${isErr ? 'bg-rose-200 dark:bg-rose-900 text-rose-800 dark:text-rose-200' : 'bg-emerald-200 dark:bg-emerald-900 text-emerald-800 dark:text-emerald-200'} flex items-center justify-center font-bold text-xs shrink-0 mt-0.5">
        ${isErr ? '!' : '✓'}
      </div>
      <div class="space-y-1">
        <h4 class="font-bold text-sm leading-none">${title}</h4>
        <p class="text-xs ${isErr ? 'text-rose-700 dark:text-rose-300' : 'text-emerald-700 dark:text-emerald-300'}">${message}</p>
        ${advice ? `<p class="text-xs font-semibold ${isErr ? 'text-rose-800 dark:text-rose-200' : 'text-emerald-800 dark:text-emerald-200'} pt-1 border-t ${isErr ? 'border-rose-200 dark:border-rose-900/60' : 'border-emerald-200 dark:border-emerald-900/60'}">Solusi: ${advice}</p>` : ''}
      </div>
    </div>
  `;
  globalAlert.classList.remove("hidden");
}

function clearAlert() {
  globalAlert.classList.add("hidden");
}

function setStep(stepNum) {
  clearAlert();
  [step1, step2, step3].forEach(el => el.classList.add("hidden"));

  const tabs = [
    { el: stepTab1, num: "1", title: "Soal Tugas", sub: "Ketik atau unggah berkas" },
    { el: stepTab2, num: "2", title: "Pilih Rujukan", sub: "Centang paper rujukan" },
    { el: stepTab3, num: "3", title: "Naskah Selesai", sub: "Periksa & unduh Word" }
  ];

  tabs.forEach((tab, idx) => {
    const s = idx + 1;
    if (!tab.el) return;
    if (s === stepNum) {
      tab.el.className = "p-3.5 rounded-xl border-2 border-stone-900 dark:border-stone-100 bg-white dark:bg-stone-900 shadow-sm transition";
      tab.el.innerHTML = `
        <div class="flex items-center space-x-2">
          <span class="w-6 h-6 rounded-full bg-stone-900 dark:bg-stone-100 text-white dark:text-stone-950 text-xs font-bold flex items-center justify-center shrink-0">${tab.num}</span>
          <span class="text-xs font-bold text-stone-900 dark:text-stone-100 truncate">${tab.title}</span>
        </div>
        <p class="text-[11px] text-stone-600 dark:text-stone-300 mt-1 pl-8 hidden sm:block">${tab.sub}</p>
      `;
      tab.el.onclick = null;
    } else if (s < stepNum) {
      tab.el.className = "p-3.5 rounded-xl border-2 border-emerald-600 dark:border-emerald-700 bg-emerald-50/70 dark:bg-emerald-950/40 cursor-pointer transition hover:bg-emerald-100/70 dark:hover:bg-emerald-950/60 shadow-sm";
      tab.el.innerHTML = `
        <div class="flex items-center space-x-2">
          <span class="w-6 h-6 rounded-full bg-emerald-600 dark:bg-emerald-500 text-white dark:text-stone-950 text-xs font-bold flex items-center justify-center shrink-0">✓</span>
          <span class="text-xs font-bold text-emerald-950 dark:text-emerald-300 truncate">${tab.title}</span>
        </div>
        <p class="text-[11px] text-emerald-700 dark:text-emerald-400 mt-1 pl-8 hidden sm:block">Klik untuk kembali</p>
      `;
      tab.el.onclick = () => setStep(s);
    } else {
      tab.el.className = "p-3.5 rounded-xl border-2 border-stone-200 dark:border-stone-800 bg-stone-100/70 dark:bg-stone-900/40 transition";
      tab.el.innerHTML = `
        <div class="flex items-center space-x-2">
          <span class="w-6 h-6 rounded-full bg-stone-200 dark:bg-stone-800 text-stone-600 dark:text-stone-300 text-xs font-bold flex items-center justify-center shrink-0">${tab.num}</span>
          <span class="text-xs font-bold text-stone-600 dark:text-stone-300 truncate">${tab.title}</span>
        </div>
        <p class="text-[11px] text-stone-500 dark:text-stone-400 mt-1 pl-8 hidden sm:block">${tab.sub}</p>
      `;
      tab.el.onclick = null;
    }
  });

  if (stepNum === 1) {
    step1.classList.remove("hidden");
    window.scrollTo({ top: 0, behavior: "smooth" });
  } else if (stepNum === 2) {
    step2.classList.remove("hidden");
    window.scrollTo({ top: 0, behavior: "smooth" });
  } else if (stepNum === 3) {
    step3.classList.remove("hidden");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
}

// 1. Health Check
async function checkSystemHealth() {
  try {
    const res = await fetch("/api/health");
    if (!res.ok) throw new Error("Server tidak merespons");
    const data = await res.json();
    if (data.gemini_configured) {
      apiStatusBadge.innerHTML = `
        <span class="w-2 h-2 rounded-full bg-emerald-500"></span>
        <span class="text-stone-700 dark:text-stone-200 font-semibold">Gemini Siap</span>
      `;
    } else {
      apiStatusBadge.innerHTML = `
        <span class="w-2 h-2 rounded-full bg-amber-500"></span>
        <span class="text-stone-700 dark:text-stone-200 font-semibold">API Key Belum Disetel</span>
      `;
    }
  } catch (err) {
    apiStatusBadge.innerHTML = `
      <span class="w-2 h-2 rounded-full bg-rose-500"></span>
      <span class="text-stone-700 dark:text-stone-200 font-semibold">Server Offline</span>
    `;
  }
}

// Search Refinement & Manual DOI Elements
const inputRefineQuery = document.getElementById("input-refine-query");
const btnRefineSearch = document.getElementById("btn-refine-search");
const btnToggleManual = document.getElementById("btn-toggle-manual");
const manualPaperWrapper = document.getElementById("manual-paper-wrapper");
const inputManualDoi = document.getElementById("input-manual-doi");
const btnAddManualPaper = document.getElementById("btn-add-manual-paper");

async function performSearch(query) {
  if (!query || query.trim().length < 3) return;
  const cleanQ = query.trim();

  btnSearch.disabled = true;
  btnSearch.innerHTML = "<span>Mencari di repositori...</span>";
  if (btnRefineSearch) {
    btnRefineSearch.disabled = true;
    btnRefineSearch.textContent = "Mencari...";
  }
  clearAlert();

  setStep(2);
  papersLoading.classList.remove("hidden");
  searchBackendInfo.classList.add("hidden");
  papersList.innerHTML = "";
  generateActions.classList.add("hidden");
  selectedPaperIds.clear();

  if (inputRefineQuery) {
    inputRefineQuery.value = cleanQ;
  }

  try {
    const res = await fetch("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: cleanQ, limit: 6 })
    });

    const data = await res.json();
    papersLoading.classList.add("hidden");
    btnSearch.disabled = false;
    btnSearch.innerHTML = "<span>Cari Naskah Terverifikasi</span>";
    if (btnRefineSearch) {
      btnRefineSearch.disabled = false;
      btnRefineSearch.textContent = "Cari Ulang";
    }

    const fetchedPapers = (data && data.papers) ? [...data.papers] : [];
    
    // Jika ada modul UT dari Langkah 1 yang sudah siap, pasang di urutan terdepan
    if (pendingManualModule) {
      const exists = fetchedPapers.some(p => p.id === pendingManualModule.id);
      if (!exists) {
        fetchedPapers.unshift(pendingManualModule);
      }
      selectedPaperIds.add(pendingManualModule.id);
    }

    if (fetchedPapers.length === 0) {
      searchBackendInfo.innerHTML = `
        <div class="space-y-1">
          <p class="font-bold text-stone-800 dark:text-stone-200">Laporan Backend Pencarian:</p>
          <p class="text-stone-600 dark:text-stone-300">${data.message || 'Tidak ada naskah yang cocok dengan kueri ini.'}</p>
          <p class="text-stone-500 dark:text-stone-400 text-xs">Kata kunci yang diproses: <span class="font-semibold text-stone-800 dark:text-stone-200">${data.query_used || cleanQ}</span></p>
        </div>
      `;
      searchBackendInfo.classList.remove("hidden");

      papersList.innerHTML = `
        <div class="p-8 text-center bg-stone-50 dark:bg-stone-900/60 rounded-2xl border border-dashed border-stone-300 dark:border-stone-700 space-y-2">
          <p class="text-sm font-bold text-stone-800 dark:text-stone-200">Naskah tidak ditemukan untuk kata kunci ini</p>
          <p class="text-xs text-stone-500 dark:text-stone-400 max-w-md mx-auto">Coba ketik kata kunci yang lebih ringkas di kotak pencarian atas, atau masukkan nomor DOI resmi jika sudah punya naskah tertentu.</p>
        </div>
      `;
      return;
    }

    currentPapers = fetchedPapers;
    
    // Tampilkan informasi backend sukses
    searchBackendInfo.innerHTML = `
      <div class="flex items-center justify-between flex-wrap gap-2">
        <div>
          <span class="font-semibold text-stone-800 dark:text-stone-200">Status Pencarian:</span> 
          <span class="text-stone-700 dark:text-stone-300">${data.message || 'Naskah berhasil ditemukan.'}</span>
        </div>
        <div class="text-stone-500 dark:text-stone-400 text-xs">
          Kueri Fokus: <span class="font-semibold text-stone-800 dark:text-stone-200">${data.query_used || cleanQ}</span>
        </div>
      </div>
    `;
    searchBackendInfo.classList.remove("hidden");

    updateSelectionState();
    renderPapersList();
  } catch (err) {
    papersLoading.classList.add("hidden");
    btnSearch.disabled = false;
    btnSearch.innerHTML = "<span>Cari Naskah Terverifikasi</span>";
    if (btnRefineSearch) {
      btnRefineSearch.disabled = false;
      btnRefineSearch.textContent = "Cari Ulang";
    }
    showAlert(
      "Gagal Menghubungi Server Backend",
      "Koneksi jaringan terputus saat menghubungi endpoint /api/search.",
      "Pastikan server di terminal masih aktif dan coba kembali."
    );
  }
}

// 2. Search Papers
formSearch.addEventListener("submit", async (e) => {
  e.preventDefault();

  const step1UtCodeVal = inputStep1UtCode ? inputStep1UtCode.value.trim() : "";
  const step1UtContentVal = inputStep1UtContent ? inputStep1UtContent.value.trim() : "";

  // Jika kode dan kutipan teks modul diisi di Langkah 1, daftarkan modul ke backend
  if (step1UtCodeVal && step1UtContentVal && step1UtContentVal.length >= 15) {
    try {
      const resModule = await fetch("/api/manual-module", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          module_title: step1UtCodeVal,
          author: "Universitas Terbuka",
          year: 2023,
          page_or_kb: "Bahan Ajar Resmi",
          content_text: step1UtContentVal
        })
      });
      if (resModule.ok) {
        pendingManualModule = await resModule.json();
      }
    } catch (err) {
      console.warn("Gagal auto-save modul UT di Langkah 1", err);
    }
  } else if (step1UtCodeVal) {
    // Sinkronkan kode atau nama modul ke form Langkah 2
    if (inputUtTitle) {
      inputUtTitle.value = step1UtCodeVal;
    }
    if (utModuleWrapper) {
      utModuleWrapper.classList.remove("hidden");
    }
  }

  performSearch(inputTopic.value);
});

if (btnRefineSearch && inputRefineQuery) {
  btnRefineSearch.addEventListener("click", () => {
    performSearch(inputRefineQuery.value);
  });
  inputRefineQuery.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      performSearch(inputRefineQuery.value);
    }
  });
}

if (btnToggleManual && manualPaperWrapper) {
  btnToggleManual.addEventListener("click", () => {
    manualPaperWrapper.classList.toggle("hidden");
    if (!manualPaperWrapper.classList.contains("hidden") && inputManualDoi) {
      inputManualDoi.focus();
    }
  });
}

if (btnAddManualPaper && inputManualDoi) {
  btnAddManualPaper.addEventListener("click", async () => {
    const val = inputManualDoi.value.trim();
    if (!val || val.length < 3) return;

    btnAddManualPaper.disabled = true;
    btnAddManualPaper.textContent = "Mencari...";
    try {
      const res = await fetch("/api/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: val, limit: 1 })
      });
      const data = await res.json();
      btnAddManualPaper.disabled = false;
      btnAddManualPaper.textContent = "Tambahkan ke Daftar";

      if (data.success && data.papers && data.papers.length > 0) {
        const newPaper = data.papers[0];
        const existingIdx = currentPapers.findIndex(p => p.id === newPaper.id);
        if (existingIdx === -1) {
          currentPapers.unshift(newPaper);
        }
        selectedPaperIds.add(newPaper.id);
        inputManualDoi.value = "";
        manualPaperWrapper.classList.add("hidden");
        updateSelectionState();
        renderPapersList();
        showAlert(
          "Naskah Berhasil Ditambahkan",
          `Naskah "${newPaper.title}" telah dimasukkan ke daftar rujukan dan dicentang otomatis.`,
          "",
          "success"
        );
      } else {
        showAlert(
          "Naskah Tidak Ditemukan",
          "Nomor DOI atau judul naskah tidak ditemukan di registri ilmiah resmi.",
          "Pastikan format DOI tepat seperti 10.xxxx/..."
        );
      }
    } catch (e) {
      btnAddManualPaper.disabled = false;
      btnAddManualPaper.textContent = "Tambahkan ke Daftar";
      showAlert("Gagal Menghubungi Server", "Periksa koneksi server lokal.");
    }
  });
}

// Step 1 UT Elements
const inputStep1UtCode = document.getElementById("input-step1-ut-code");
const step1UtLookupSpinner = document.getElementById("step1-ut-lookup-spinner");
const step1UtDetectResult = document.getElementById("step1-ut-detect-result");
const btnToggleStep1UtContent = document.getElementById("btn-toggle-step1-ut-content");
const step1UtContentWrapper = document.getElementById("step1-ut-content-wrapper");
const inputStep1UtContent = document.getElementById("input-step1-ut-content");
const btnPickStep1Screenshot = document.getElementById("btn-pick-step1-screenshot");
const step1UploadScreenshot = document.getElementById("step1-upload-screenshot");
const step1OcrStatus = document.getElementById("step1-ocr-status");

// Step 2 UT Module Elements & Handlers
const btnToggleUtModule = document.getElementById("btn-toggle-ut-module");
const utModuleWrapper = document.getElementById("ut-module-wrapper");
const inputUtTitle = document.getElementById("input-ut-title");
const utLookupSpinner = document.getElementById("ut-lookup-spinner");
const utDetectResult = document.getElementById("ut-detect-result");
const inputUtAuthor = document.getElementById("input-ut-author");
const inputUtPage = document.getElementById("input-ut-page");
const inputUtContent = document.getElementById("input-ut-content");
const btnPickStep2Screenshot = document.getElementById("btn-pick-step2-screenshot");
const step2UploadScreenshot = document.getElementById("step2-upload-screenshot");
const step2OcrStatus = document.getElementById("step2-ocr-status");
const btnSaveUtModule = document.getElementById("btn-save-ut-module");

// Reusable UT Lookup Handler
function attachUtLookup(inputEl, spinnerEl, resultEl, onSelectTitle) {
  if (!inputEl || !resultEl) return;
  let timer = null;
  let lastQuery = "";

  async function performLookup(val) {
    const query = val.trim();
    if (!query || query.length < 2) {
      resultEl.classList.add("hidden");
      resultEl.innerHTML = "";
      return;
    }

    if (query === lastQuery) return;
    lastQuery = query;

    if (spinnerEl) spinnerEl.classList.remove("hidden");

    try {
      const res = await fetch(`/api/ut-course-lookup?query=${encodeURIComponent(query)}`);
      const data = await res.json();
      if (spinnerEl) spinnerEl.classList.add("hidden");

      if (data.found && data.course) {
        resultEl.classList.remove("hidden");
        const course = data.course;
        
        if (data.exact) {
          resultEl.innerHTML = `
            <div class="flex items-center justify-between gap-2 flex-wrap">
              <div class="space-y-0.5">
                <div class="flex items-center gap-1.5 font-bold text-emerald-950 dark:text-emerald-300">
                  <svg class="w-3.5 h-3.5 text-emerald-700 dark:text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7"/></svg>
                  <span>Terdeteksi Resmi di BMP UT:</span>
                </div>
                <div class="text-xs font-semibold text-emerald-900 dark:text-emerald-200">
                  ${course.kode} - ${course.nama} <span class="ml-1 text-[10px] bg-emerald-200 dark:bg-emerald-900 text-emerald-900 dark:text-emerald-200 font-bold px-1.5 py-0.5 rounded">${course.edisi}</span>
                </div>
              </div>
              <button 
                type="button" 
                class="btn-apply-ut-detected px-2.5 py-1 rounded bg-emerald-900 hover:bg-emerald-800 dark:bg-emerald-700 dark:hover:bg-emerald-600 text-white font-semibold text-[11px] shrink-0 transition shadow-sm"
              >
                Gunakan Judul Resmi
              </button>
            </div>
          `;
          const btnApply = resultEl.querySelector(".btn-apply-ut-detected");
          if (btnApply) {
            btnApply.addEventListener("click", () => {
              inputEl.value = course.formatted_title;
              resultEl.classList.add("hidden");
              if (onSelectTitle) onSelectTitle(course.formatted_title, course);
            });
          }
        } else if (data.suggestions && data.suggestions.length > 0) {
          const pillButtons = data.suggestions.map((s) => `
            <button 
              type="button" 
              class="btn-select-suggestion text-left px-2 py-1 rounded bg-emerald-200/80 dark:bg-emerald-900/60 hover:bg-emerald-300 dark:hover:bg-emerald-800 text-emerald-950 dark:text-emerald-200 font-medium text-[11px] transition"
              data-title="${s.formatted_title}"
            >
              ${s.kode} ${s.nama}
            </button>
          `).join("");

          resultEl.innerHTML = `
            <div class="space-y-1.5">
              <div class="text-[11px] font-semibold text-emerald-950 dark:text-emerald-300">Pilih dari katalog mata kuliah UT yang cocok:</div>
              <div class="flex flex-wrap gap-1.5">
                ${pillButtons}
              </div>
            </div>
          `;

          resultEl.querySelectorAll(".btn-select-suggestion").forEach(btn => {
            btn.addEventListener("click", (e) => {
              const pickedTitle = e.currentTarget.getAttribute("data-title");
              if (pickedTitle) {
                inputEl.value = pickedTitle;
                resultEl.classList.add("hidden");
                if (onSelectTitle) onSelectTitle(pickedTitle);
              }
            });
          });
        }
      } else {
        if (query.length >= 4) {
          resultEl.classList.remove("hidden");
          resultEl.innerHTML = `
            <div class="text-xs text-stone-600 dark:text-stone-400 py-1">
              <span class="font-semibold text-stone-800 dark:text-stone-200">Kode belum tercatat di katalog:</span>
              <span class="font-mono font-bold text-stone-900 dark:text-stone-100">${query.toUpperCase()}</span>
              <p class="text-[11px] text-stone-500 dark:text-stone-400 mt-0.5">Kode ini tetap dapat kamu pakai sebagai rujukan atau kamu lengkapi dengan judul manual.</p>
            </div>
          `;
        } else {
          resultEl.classList.add("hidden");
          resultEl.innerHTML = "";
        }
      }
    } catch (e) {
      if (spinnerEl) spinnerEl.classList.add("hidden");
    }
  }

  inputEl.addEventListener("input", (e) => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      performLookup(e.target.value);
    }, 200);
  });

  inputEl.addEventListener("paste", () => {
    setTimeout(() => {
      performLookup(inputEl.value);
    }, 50);
  });
}

// Inisialisasi auto-detect di Langkah 1 & Langkah 2
if (btnToggleStep1UtContent && step1UtContentWrapper) {
  btnToggleStep1UtContent.addEventListener("click", () => {
    step1UtContentWrapper.classList.toggle("hidden");
    if (!step1UtContentWrapper.classList.contains("hidden") && inputStep1UtContent) {
      inputStep1UtContent.focus();
    }
  });
}

attachUtLookup(inputStep1UtCode, step1UtLookupSpinner, step1UtDetectResult, (title) => {
  if (inputUtTitle) inputUtTitle.value = title;
});

attachUtLookup(inputUtTitle, utLookupSpinner, utDetectResult, (title) => {
  if (inputStep1UtCode) inputStep1UtCode.value = title;
});

if (btnToggleUtModule && utModuleWrapper) {
  btnToggleUtModule.addEventListener("click", () => {
    utModuleWrapper.classList.toggle("hidden");
    if (!utModuleWrapper.classList.contains("hidden") && inputUtTitle) {
      inputUtTitle.focus();
    }
  });
}

if (btnSaveUtModule && inputUtContent && inputUtTitle) {
  btnSaveUtModule.addEventListener("click", async () => {
    const titleVal = inputUtTitle.value.trim();
    const contentVal = inputUtContent.value.trim();

    if (!titleVal) {
      showAlert("Nama Modul Diperlukan", "Ketik nama atau kode modul kuliah, misalnya: FSSI4106 English for Translation.");
      return;
    }
    if (!contentVal || contentVal.length < 15) {
      showAlert("Teks Modul Kurang Panjang", "Tempelkan minimal beberapa kalimat atau paragraf materi teori dari pustaka.ut.ac.id.");
      return;
    }

    btnSaveUtModule.disabled = true;
    btnSaveUtModule.textContent = "Menyimpan Modul...";

    try {
      const res = await fetch("/api/manual-module", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          module_title: titleVal,
          author: "Universitas Terbuka",
          year: 2023,
          page_or_kb: "Bahan Ajar Resmi",
          content_text: contentVal
        })
      });

      const newModule = await res.json();
      btnSaveUtModule.disabled = false;
      btnSaveUtModule.textContent = "Gunakan Modul Ini Sebagai Rujukan Tugas";

      if (res.ok && newModule && newModule.id) {
        currentPapers.unshift(newModule);
        selectedPaperIds.add(newModule.id);
        
        inputUtTitle.value = "";
        inputUtContent.value = "";
        utModuleWrapper.classList.add("hidden");

        updateSelectionState();
        renderPapersList();

        showAlert(
          "Modul Bahan Ajar Berhasil Digunakan",
          `Modul "${newModule.title}" telah dijadikan rujukan utama dan siap disitir ke dalam naskah tugas.`,
          "",
          "success"
        );
      } else {
        showAlert("Gagal Menyimpan Modul", "Terjadi kesalahan saat memproses data modul.");
      }
    } catch (e) {
      btnSaveUtModule.disabled = false;
      btnSaveUtModule.textContent = "Gunakan Modul Ini Sebagai Rujukan Tugas";
      showAlert("Gagal Menghubungi Server", "Periksa koneksi server lokal.");
    }
  });
}

// Handler Ekstraksi Screenshot OCR
async function processScreenshotFile(file, targetTextarea, statusEl) {
  if (!file || !file.type.startsWith("image/")) {
    showAlert("Format Berkas Tidak Sesuai", "Pilih berkas gambar tangkapan layar seperti PNG, JPG, atau WebP.");
    return;
  }

  if (statusEl) statusEl.classList.remove("hidden");

  try {
    const base64Data = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });

    const res = await fetch("/api/extract-screenshot", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image_data: base64Data })
    });

    const data = await res.json();
    if (statusEl) statusEl.classList.add("hidden");

    if (data.success && data.extracted_text) {
      const currentText = targetTextarea ? targetTextarea.value.trim() : "";
      if (targetTextarea) {
        if (currentText) {
          targetTextarea.value = currentText + "\n\n" + data.extracted_text;
        } else {
          targetTextarea.value = data.extracted_text;
        }
      }
      showAlert(
        "Teks Modul Berhasil Diekstrak",
        `Berhasil membaca materi modul (${data.extracted_text.length} karakter) tanpa watermark. Teks otomatis masuk ke kotak materi.`,
        "",
        "success"
      );
    } else {
      showAlert(
        "Gagal Membaca Gambar",
        data.message || data.detail || "Teks pada gambar tidak terbaca jelas.",
        "Pastikan tangkapan layar modul cukup tajam dan tidak terpotong."
      );
    }
  } catch (err) {
    if (statusEl) statusEl.classList.add("hidden");
    showAlert("Gagal Menghubungi Layanan OCR", "Periksa koneksi server lokal dan konfigurasi API key.");
  }
}

// Event Listeners Unggah Berkas Screenshot
if (btnPickStep1Screenshot && step1UploadScreenshot) {
  btnPickStep1Screenshot.addEventListener("click", () => {
    step1UploadScreenshot.click();
  });
  step1UploadScreenshot.addEventListener("change", (e) => {
    if (e.target.files && e.target.files[0]) {
      processScreenshotFile(e.target.files[0], inputStep1UtContent, step1OcrStatus);
      e.target.value = "";
    }
  });
}

if (btnPickStep2Screenshot && step2UploadScreenshot) {
  btnPickStep2Screenshot.addEventListener("click", () => {
    step2UploadScreenshot.click();
  });
  step2UploadScreenshot.addEventListener("change", (e) => {
    if (e.target.files && e.target.files[0]) {
      processScreenshotFile(e.target.files[0], inputUtContent, step2OcrStatus);
      e.target.value = "";
    }
  });
}

// Global Paste Listener (Ctrl+V Gambar dari Snipping Tool / Ruang Baca Virtual)
window.addEventListener("paste", async (e) => {
  const clipboardItems = e.clipboardData ? e.clipboardData.items : [];
  let imageItem = null;

  for (let i = 0; i < clipboardItems.length; i++) {
    if (clipboardItems[i].type.startsWith("image/")) {
      imageItem = clipboardItems[i];
      break;
    }
  }

  if (!imageItem) return;

  const file = imageItem.getAsFile();
  if (!file) return;

  const isStep2Active = !step2.classList.contains("hidden");
  if (isStep2Active) {
    if (utModuleWrapper) utModuleWrapper.classList.remove("hidden");
    e.preventDefault();
    processScreenshotFile(file, inputUtContent, step2OcrStatus);
  } else {
    if (step1UtContentWrapper) step1UtContentWrapper.classList.remove("hidden");
    e.preventDefault();
    processScreenshotFile(file, inputStep1UtContent, step1OcrStatus);
  }
});




function renderPapersList() {
  papersList.innerHTML = "";
  generateActions.classList.remove("hidden");

  currentPapers.forEach((paper) => {
    const card = document.createElement("div");
    const isSelected = selectedPaperIds.has(paper.id);
    const isUtBmp = paper.id.startsWith("bmp_") || (paper.venue && paper.venue.includes("Universitas Terbuka"));

    card.className = `p-4 sm:p-5 rounded-xl border transition cursor-pointer ${
      isUtBmp
        ? (isSelected ? "border-emerald-700 dark:border-emerald-500 bg-emerald-50/80 dark:bg-emerald-950/40 ring-1 ring-emerald-700 dark:ring-emerald-500" : "border-emerald-300 dark:border-emerald-900/60 hover:border-emerald-500 dark:hover:border-emerald-700 bg-white dark:bg-stone-900")
        : (isSelected ? "border-stone-900 dark:border-stone-200 bg-stone-50 dark:bg-stone-800/80 ring-1 ring-stone-900 dark:ring-stone-200" : "border-stone-200 dark:border-stone-800 hover:border-stone-400 dark:hover:border-stone-600 bg-white dark:bg-stone-900")
    }`;

    const authors = paper.authors.slice(0, 3).join(", ") + (paper.authors.length > 3 ? " et al." : "");
    const yearStr = paper.year ? paper.year : "n.d.";

    const statusBadge = isUtBmp
      ? `<span class="inline-flex items-center text-emerald-800 dark:text-emerald-300 font-semibold"><span class="w-1.5 h-1.5 rounded-full bg-emerald-600 dark:bg-emerald-400 mr-1.5"></span>Materi Pokok UT Siap Disitir</span>`
      : `<span class="inline-flex items-center text-stone-700 dark:text-stone-300 font-medium"><span class="w-1.5 h-1.5 rounded-full bg-emerald-500 mr-1.5"></span>Naskah PDF Asli Ada</span>`;

    card.innerHTML = `
      <div class="flex items-start justify-between gap-3">
        <div class="flex-1">
          <div class="flex items-center space-x-2 text-xs font-semibold text-stone-500 dark:text-stone-400 mb-1">
            <span class="px-2 py-0.5 rounded ${isUtBmp ? 'bg-emerald-100 dark:bg-emerald-950 text-emerald-900 dark:text-emerald-300 border border-emerald-300/40 dark:border-emerald-800' : 'bg-stone-100 dark:bg-stone-800 text-stone-700 dark:text-stone-300'}">${yearStr}</span>
            <span class="${isUtBmp ? 'text-emerald-800 dark:text-emerald-300 font-bold' : ''}">${paper.venue || "Publikasi Akademik"}</span>
          </div>
          <h4 class="text-sm font-bold text-stone-900 dark:text-stone-100 leading-snug">${paper.title}</h4>
          <p class="text-xs text-stone-600 dark:text-stone-400 mt-1">${authors}</p>
          <p class="text-xs text-stone-500 dark:text-stone-400 mt-2 line-clamp-2">${paper.abstract}</p>
          
          <div class="mt-3 flex items-center space-x-3 text-xs">
            ${statusBadge}
            ${paper.scholar_url ? `<a href="${paper.scholar_url}" target="_blank" rel="noopener" class="text-stone-500 dark:text-stone-400 hover:text-stone-900 dark:hover:text-stone-200 underline" onclick="event.stopPropagation()">Rujukan Asli</a>` : ""}
            ${paper.doi ? `<a href="${paper.doi}" target="_blank" rel="noopener" class="text-stone-400 dark:text-stone-500 hover:text-stone-700 dark:hover:text-stone-300 underline" onclick="event.stopPropagation()">DOI</a>` : ""}
          </div>
        </div>
        <div class="shrink-0 mt-1">
          <input type="checkbox" class="w-4 h-4 rounded border-stone-300 dark:border-stone-700 text-stone-900 focus:ring-stone-900 dark:bg-stone-900" ${isSelected ? "checked" : ""}>
        </div>
      </div>
    `;

    card.addEventListener("click", () => {
      if (selectedPaperIds.has(paper.id)) {
        selectedPaperIds.delete(paper.id);
      } else {
        selectedPaperIds.add(paper.id);
      }
      updateSelectionState();
      renderPapersList();
    });

    papersList.appendChild(card);
  });

  updateSelectionState();
}

function updateSelectionState() {
  const count = selectedPaperIds.size;
  selectedCountLabel.textContent = `${count} naskah dipilih`;
  btnGenerate.disabled = count === 0;
}

btnBackStep1.addEventListener("click", () => {
  setStep(1);
});

// Stepper Progress Animation
function resetProgressLogs() {
  [logStep1, logStep2, logStep3, logStep4].forEach(el => {
    el.className = "flex items-center space-x-2 text-stone-400 dark:text-stone-500";
    el.querySelector("span:first-child").className = "w-2 h-2 rounded-full bg-stone-300 dark:bg-stone-700";
  });
}

function setStepActive(stepEl) {
  stepEl.className = "flex items-center space-x-2 text-stone-900 dark:text-stone-100 font-semibold";
  stepEl.querySelector("span:first-child").className = "w-2 h-2 rounded-full bg-stone-900 dark:bg-stone-100 animate-ping";
}

function setStepDone(stepEl) {
  stepEl.className = "flex items-center space-x-2 text-emerald-700 dark:text-emerald-400 font-medium";
  stepEl.querySelector("span:first-child").className = "w-2 h-2 rounded-full bg-emerald-500 dark:bg-emerald-400";
}

// 3. Generate Draft
btnGenerate.addEventListener("click", async () => {
  if (selectedPaperIds.size === 0) return;

  setStep(3);
  generatingIndicator.classList.remove("hidden");
  resultContainer.classList.add("hidden");
  resetProgressLogs();

  // Jalankan animasi status kerja backend
  setStepActive(logStep1);
  genStepTitle.textContent = "Tahap 1: Mengunduh berkas PDF fisik ke laptop...";

  const t1 = setTimeout(() => {
    setStepDone(logStep1);
    setStepActive(logStep2);
    genStepTitle.textContent = "Tahap 2: Membedah isi teks dan nomor halaman...";
  }, 1000);

  const t2 = setTimeout(() => {
    setStepDone(logStep2);
    setStepActive(logStep3);
    genStepTitle.textContent = "Tahap 3: Merangkai naskah via Gemini...";
  }, 2200);

  const t3 = setTimeout(() => {
    setStepDone(logStep3);
    setStepActive(logStep4);
    genStepTitle.textContent = "Tahap 4: Mengompilasi berkas docx dan pdf format A4...";
  }, 3800);

  try {
    let targetWords = 1000;
    const lenChoice = selectLength ? selectLength.value : "sedang";
    if (lenChoice === "ringkas") {
      targetWords = 400;
    } else if (lenChoice === "sedang") {
      targetWords = 950;
    } else if (lenChoice === "panjang") {
      targetWords = 1800;
    } else if (lenChoice === "kustom") {
      targetWords = parseInt(inputCustomWords.value) || 1200;
    }

    const payload = {
      topic: inputTopic.value.trim(),
      format_type: selectFormat ? selectFormat.value : "makalah",
      target_length: lenChoice,
      target_words: targetWords,
      paragraph_depth: selectDepth ? selectDepth.value : "standar",
      tone: selectTone.value,
      paper_ids: Array.from(selectedPaperIds),
      custom_instructions: inputInstructions.value.trim()
    };

    const res = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    clearTimeout(t1);
    clearTimeout(t2);
    clearTimeout(t3);

    const data = await res.json();
    generatingIndicator.classList.add("hidden");

    if (!res.ok || !data.success) {
      const errDetail = data.detail || "Gagal menyusun naskah tugas.";
      setStep(2);
      showAlert(
        "Kendala pada Proses Generasi Naskah",
        errDetail,
        "Tekan tombol 'Mulai Tulis Naskah Tugas' sekali lagi. Sistem cadangan akan mencoba varian model lain secara otomatis."
      );
      return;
    }

    currentTaskId = data.task_id;
    renderResult(data);
  } catch (err) {
    clearTimeout(t1);
    clearTimeout(t2);
    clearTimeout(t3);
    generatingIndicator.classList.add("hidden");
    setStep(2);
    showAlert(
      "Gagal Menghubungi Server Backend",
      "Koneksi ke endpoint /api/generate terputus atau timeout.",
      "Periksa status server di terminal dan coba ulangi proses."
    );
  }
});

function renderResult(data) {
  resultContainer.classList.remove("hidden");
  resultTitle.textContent = data.title;
  resultStats.textContent = `Sekitar ${data.word_count} kata - Menggunakan seluruh ${data.references.length} naskah rujukan terverifikasi`;

  // Render Bukti Sitasi & Transparansi Naskah
  const evidenceList = document.getElementById("evidence-list");
  const evidenceCountBadge = document.getElementById("evidence-count-badge");
  
  if (evidenceList && data.evidence && data.evidence.length > 0) {
    if (evidenceCountBadge) {
      evidenceCountBadge.textContent = `${data.evidence.length} Sumber Naskah`;
    }
    let evHtml = "";
    data.evidence.forEach(ev => {
      const isFullPdf = ev.has_full_pdf;
      const badgeStatus = isFullPdf 
        ? `<span class="px-2 py-0.5 rounded bg-emerald-100 dark:bg-emerald-950/80 text-emerald-800 dark:text-emerald-300 text-xs font-semibold border border-emerald-300/40 dark:border-emerald-800">Naskah Fisik PDF Terunduh</span>`
        : `<span class="px-2 py-0.5 rounded bg-amber-100 dark:bg-amber-950/80 text-amber-800 dark:text-amber-300 text-xs font-semibold border border-amber-300/40 dark:border-amber-800">Abstrak & Metadata Resmi</span>`;
      
      const citeBadge = ev.citation_count > 0 
        ? `<span class="px-2 py-0.5 rounded bg-stone-200 dark:bg-stone-800 text-stone-800 dark:text-stone-200 text-xs font-medium">${ev.citation_count} kali disitir di teks</span>`
        : `<span class="px-2 py-0.5 rounded bg-stone-100 dark:bg-stone-800/60 text-stone-500 dark:text-stone-400 text-xs">Disitir di analisis</span>`;

      let snipHtml = "";
      if (ev.snippets && ev.snippets.length > 0) {
        snipHtml = `<div class="mt-2.5 space-y-1.5">`;
        ev.snippets.forEach(sn => {
          snipHtml += `
            <div class="p-2.5 rounded-lg bg-white dark:bg-stone-900 border border-stone-200 dark:border-stone-700 text-xs text-stone-700 dark:text-stone-300 leading-relaxed">
              <span class="font-bold text-stone-900 dark:text-stone-100">[Bukti Teks Halaman ${sn.page}]:</span> "${sn.text}"
            </div>
          `;
        });
        snipHtml += `</div>`;
      }

      evHtml += `
        <div class="p-4 rounded-xl border border-stone-200 dark:border-stone-800 bg-stone-100/70 dark:bg-stone-900/60">
          <div class="flex flex-wrap items-center gap-2 mb-1.5">
            ${badgeStatus}
            ${citeBadge}
            <span class="text-xs text-stone-500 dark:text-stone-400">${ev.venue || "Publikasi Akademik"} (${ev.year || "n.d."})</span>
          </div>
          <h4 class="text-sm font-bold text-stone-900 dark:text-stone-100 leading-snug">${ev.title}</h4>
          <p class="text-xs text-stone-600 dark:text-stone-400 mt-0.5">${ev.authors}</p>
          ${snipHtml}
          <div class="mt-2.5 flex items-center space-x-3 text-xs">
            ${ev.doi ? `<a href="${ev.doi}" target="_blank" rel="noopener" class="text-stone-500 dark:text-stone-400 hover:text-stone-900 dark:hover:text-stone-200 underline">Cek DOI Resmi</a>` : ""}
            <a href="https://scholar.google.com/scholar?q=${encodeURIComponent(ev.title)}" target="_blank" rel="noopener" class="text-stone-500 dark:text-stone-400 hover:text-stone-900 dark:hover:text-stone-200 underline">Cek Google Scholar</a>
          </div>
        </div>
      `;
    });
    evidenceList.innerHTML = evHtml;
  }

  let previewHtml = `<h1 class="text-xl font-bold text-center tracking-tight uppercase mb-8 text-stone-900 dark:text-stone-100">${data.title}</h1>`;

  data.sections.forEach(sec => {
    const headingHtml = (sec.heading && sec.heading.trim())
      ? `<h2 class="text-sm font-bold uppercase tracking-wider text-stone-900 dark:text-stone-100 mb-2">${sec.heading}</h2>`
      : "";
    previewHtml += `
      <div class="mb-6">
        ${headingHtml}
        <div class="text-stone-700 dark:text-stone-300 whitespace-pre-line leading-relaxed">${sec.content}</div>
      </div>
    `;
  });

  const sampleText = (data.title + " " + (data.sections[0] ? data.sections[0].content : "")).toLowerCase();
  const isEnDoc = ["the", "and", "is", "of", "to", "in", "urban", "living"].some(w => sampleText.includes(w));
  const refHeader = isEnDoc ? "REFERENCES" : "DAFTAR PUSTAKA";

  previewHtml += `
    <div class="mt-8 pt-6 border-t border-stone-200 dark:border-stone-800">
      <h2 class="text-sm font-bold uppercase tracking-wider text-stone-900 dark:text-stone-100 mb-3">${refHeader}</h2>
      <ul class="space-y-2 text-xs text-stone-600 dark:text-stone-400">
  `;

  data.references.forEach(ref => {
    const authors = ref.authors.join(", ");
    previewHtml += `
      <li class="pl-4 -indent-4">
        ${authors} (${ref.year || "n.d."}). <em>${ref.title}</em>. ${ref.venue || "Publikasi Ilmiah"}. ${ref.doi || ""}
      </li>
    `;
  });

  previewHtml += `</ul></div>`;
  previewContent.innerHTML = previewHtml;
}


// 4. Downloads & Restart
btnDownloadDocx.addEventListener("click", () => {
  if (!currentTaskId) return;
  window.location.href = `/api/download/docx/${currentTaskId}`;
});

btnDownloadPdf.addEventListener("click", () => {
  if (!currentTaskId) return;
  window.location.href = `/api/download/pdf/${currentTaskId}`;
});

function resetToStep1() {
  inputTopic.value = "";
  inputInstructions.value = "";
  selectedPaperIds.clear();
  currentTaskId = null;
  setStep(1);
}

btnRestart.addEventListener("click", resetToStep1);

const btnTopRestart = document.getElementById("btn-top-restart");
if (btnTopRestart) {
  btnTopRestart.addEventListener("click", resetToStep1);
}

// 5. Theme Toggle (Light / Dark)
const btnToggleTheme = document.getElementById("btn-toggle-theme");
const iconSun = document.getElementById("icon-sun");
const iconMoon = document.getElementById("icon-moon");

function applyTheme(isDark) {
  if (isDark) {
    document.documentElement.classList.add("dark");
    document.documentElement.setAttribute("data-theme", "dark");
    if (iconSun && iconMoon) {
      iconSun.classList.remove("hidden");
      iconMoon.classList.add("hidden");
    }
  } else {
    document.documentElement.classList.remove("dark");
    document.documentElement.setAttribute("data-theme", "light");
    if (iconSun && iconMoon) {
      iconSun.classList.add("hidden");
      iconMoon.classList.remove("hidden");
    }
  }
}

if (btnToggleTheme) {
  const savedTheme = localStorage.getItem("atc-theme");
  const prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  const initialDark = savedTheme ? savedTheme === "dark" : prefersDark;
  applyTheme(initialDark);

  btnToggleTheme.addEventListener("click", () => {
    const isDarkNow = document.documentElement.classList.contains("dark");
    const nextDark = !isDarkNow;
    applyTheme(nextDark);
    localStorage.setItem("atc-theme", nextDark ? "dark" : "light");
  });
}

// Init
checkSystemHealth();
