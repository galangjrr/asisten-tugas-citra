const { app, BrowserWindow, ipcMain, session, shell } = require("electron");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const net = require("node:net");
const path = require("node:path");
const { fillAnswer } = require("./tuton-fill");
const { parseUsertext, parseDashboard } = require("./tuton-account");

const HOST = "127.0.0.1";
const ROOT_DIR = path.join(__dirname, "..");
// Tinggi overlay tombol jendela disamakan dengan header aplikasi h-14
const TITLEBAR_HEIGHT = 56;
// Warna simbol tombol jendela mengikuti token teks sekunder stone-600 dan dark stone-300
const SYMBOL_COLOR = { light: "#57534e", dark: "#d6d3d1" };

// Folder data permanen: .env, tugas tersimpan, dan profil Chromium. Tidak ikut terhapus saat aplikasi di-update.
const DATA_DIR = path.join(process.env.LOCALAPPDATA || app.getPath("appData"), "AsistenTugasCitra");

// Tuton UT berbasis Moodle. ATC_TUTON_URL hanya untuk uji lokal di mode dev.
const TUTON_URL = (!app.isPackaged && process.env.ATC_TUTON_URL) || "https://elearning.ut.ac.id/";

// ATC_DEBUG_PORT membuka port DevTools Protocol di 127.0.0.1 untuk inspeksi halaman, hanya di mode dev
if (!app.isPackaged && /^\d+$/.test(process.env.ATC_DEBUG_PORT || "")) {
  app.commandLine.appendSwitch("remote-debugging-port", process.env.ATC_DEBUG_PORT);
}

let backend = null;
let win = null;
let tutonWin = null;

// Profil Chromium disimpan permanen supaya localStorage seperti nama dan NIM tetap ingat
app.setPath("userData", path.join(DATA_DIR, "electron"));

function findFreePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.once("error", reject);
    srv.listen(0, HOST, () => {
      const { port } = srv.address();
      srv.close(() => resolve(port));
    });
  });
}

function waitForServer(port, timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    const attempt = () => {
      const sock = net.connect(port, HOST);
      sock.once("connect", () => {
        sock.destroy();
        resolve();
      });
      sock.once("error", () => {
        sock.destroy();
        if (Date.now() > deadline) return reject(new Error("Server lokal gagal menyala"));
        setTimeout(attempt, 150);
      });
    };
    attempt();
  });
}

// Versi terpasang memakai exe backend hasil PyInstaller, versi dev memakai python langsung
// stdin dibiarkan berupa pipe yang tidak pernah ditulis. Kalau Electron mati dengan cara apa pun,
// Windows menutup pipe itu dan backend yang menunggu stdin langsung ikut berhenti.
function startBackend(port) {
  const options = { windowsHide: true, stdio: ["pipe", "ignore", "ignore"] };
  const args = [String(port), "--exit-with-parent"];
  if (app.isPackaged) {
    const exe = path.join(process.resourcesPath, "backend", "AsistenTugasCitraServer.exe");
    // Backend membaca .env dari cwd, jadi cwd diarahkan ke folder data permanen
    fs.mkdirSync(DATA_DIR, { recursive: true });
    return spawn(exe, args, { ...options, cwd: DATA_DIR });
  }
  const python = process.env.PYTHON || "python";
  return spawn(python, [path.join(ROOT_DIR, "run_app.py"), ...args], { ...options, cwd: ROOT_DIR });
}

const loadingPage = `data:text/html;charset=utf-8,${encodeURIComponent(`<!doctype html>
<html><body style="margin:0;height:100vh;display:grid;place-items:center;background:#0c0a09;color:#a8a29e;font:500 13px 'Segoe UI',sans-serif;-webkit-app-region:drag">
Menyiapkan Asisten Tugas Citra</body></html>`)}`;

function createWindow() {
  win = new BrowserWindow({
    width: 1200,
    height: 820,
    minWidth: 400,
    minHeight: 500,
    title: "Asisten Tugas Citra",
    // Versi terpasang otomatis memakai ikon exe dari electron-builder
    icon: app.isPackaged ? undefined : path.join(ROOT_DIR, "assets", "icon.ico"),
    backgroundColor: "#0c0a09",
    // Title bar bawaan disembunyikan, tombol jendela native dipasang di atas header web dengan latar transparan
    titleBarStyle: "hidden",
    titleBarOverlay: { color: "#00000000", symbolColor: SYMBOL_COLOR.dark, height: TITLEBAR_HEIGHT },
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      sandbox: true,
    },
  });
  win.removeMenu();

  // Tautan Tuton dan RBV dibuka di jendela Tuton supaya login, F9, dan Pakai soal ini tetap jalan.
  // Tautan eksternal lain seperti DOI dibuka di browser bawaan, bukan di jendela aplikasi.
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (isTutonUrl(url)) openTuton(url);
    else if (url.startsWith("http://") || url.startsWith("https://")) shell.openExternal(url);
    return { action: "deny" };
  });

  win.loadURL(loadingPage);
}

function isTutonUrl(url) {
  try {
    const { protocol, hostname, origin } = new URL(url);
    if (!app.isPackaged && process.env.ATC_TUTON_URL && origin === new URL(process.env.ATC_TUTON_URL).origin) return true;
    return protocol === "https:" && (hostname === "ut.ac.id" || hostname.endsWith(".ut.ac.id"));
  } catch (err) {
    return false;
  }
}

const LOGIN_HOSTS = ["login.microsoftonline.com", "login.live.com"];

function isLoginPopup(url) {
  if (url === "about:blank") return true;
  try {
    const { protocol, hostname } = new URL(url);
    return protocol === "https:" && LOGIN_HOSTS.includes(hostname);
  } catch (err) {
    return false;
  }
}

// Jendela Tuton memakai sesi terpisah yang disimpan permanen, jadi login cukup sekali dan cookie Tuton
// tidak bercampur dengan halaman Asisten. Password tidak pernah dibaca, login diketik sendiri oleh pengguna.
function openTuton(url = TUTON_URL) {
  if (tutonWin && !tutonWin.isDestroyed()) {
    if (tutonWin.isMinimized()) tutonWin.restore();
    tutonWin.focus();
    // Pindah situs saja, misal Tuton ke RBV. Halaman Tuton yang sedang dibuka, mungkin berisi jawaban setengah jadi, tidak dimuat ulang.
    if (new URL(url).hostname !== new URL(tutonWin.webContents.getURL() || url).hostname) tutonWin.loadURL(url);
    return;
  }
  tutonWin = new BrowserWindow({
    width: 1100,
    height: 820,
    minWidth: 400,
    minHeight: 500,
    title: "Tuton UT",
    icon: app.isPackaged ? undefined : path.join(ROOT_DIR, "assets", "icon.ico"),
    autoHideMenuBar: true,
    webPreferences: {
      partition: "persist:tuton",
      preload: path.join(__dirname, "tuton-preload.js"),
      contextIsolation: true,
      sandbox: true,
    },
  });
  tutonWin.removeMenu();
  tutonWin.webContents.setWindowOpenHandler(({ url }) => {
    // Login MyUT membuka popup Microsoft yang dimulai dari about:blank. Popup itu harus jadi jendela anak
    // dengan sesi yang sama, kalau tidak halaman MyUT tidak pernah menerima hasil login dan tombol Masuk terlihat diam.
    if (isLoginPopup(url) && isTutonUrl(tutonWin.webContents.getURL())) {
      return { action: "allow", overrideBrowserWindowOptions: { width: 520, height: 720, autoHideMenuBar: true } };
    }
    // Tautan Tuton yang membuka tab baru tetap dibuka di jendela ini, tautan luar ke browser bawaan
    if (isTutonUrl(url)) tutonWin.loadURL(url);
    else if (url.startsWith("http://") || url.startsWith("https://")) shell.openExternal(url);
    return { action: "deny" };
  });
  tutonWin.on("closed", () => {
    tutonWin = null;
  });
  tutonWin.on("focus", () => { rbvTarget = tutonWin; });
  listenF9(tutonWin.webContents);
  // Pembaca buku RBV bisa terbuka sebagai jendela anak. Jendela itu ikut mendengar F9 dan jadi sasaran jepret.
  tutonWin.webContents.on("did-create-window", (child) => {
    child.removeMenu();
    listenF9(child.webContents);
    child.on("focus", () => { rbvTarget = child; });
    rbvTarget = child;
  });

  tutonWin.loadURL(url);
}

// Jendela Tuton atau jendela anaknya yang terakhir difokus, jadi F9 dari jendela Asisten memotret halaman yang sedang dibaca
let rbvTarget = null;

// Tombol pintas F9 untuk jepret lembar bacaan RBV secara pasif dari luar tanpa menyentuh DOM
function listenF9(contents) {
  contents.on("before-input-event", (event, input) => {
    if (input.type === "keyDown" && input.key === "F9" && !input.isAutoRepeat) {
      event.preventDefault();
      captureRbvPage(BrowserWindow.fromWebContents(contents));
    }
  });
}

let isCapturingRbv = false;

async function captureRbvPage(target) {
  if (isCapturingRbv) return;
  const source = [target, rbvTarget, tutonWin].find((w) => w && !w.isDestroyed());
  if (!source) {
    openTuton();
    return;
  }
  if (!win || win.isDestroyed()) return;
  isCapturingRbv = true;
  try {
    // Jendela yang diminimize tidak digambar ulang, hasil jepretnya kosong
    if (source.isMinimized()) source.restore();
    const image = await source.webContents.capturePage();
    if (image.isEmpty()) {
      win.webContents.send("rbv-screenshot-captured", { error: "Halaman RBV belum tampil di layar. Buka jendela bukunya, lalu tekan F9 lagi." });
      return;
    }
    win.webContents.send("rbv-screenshot-captured", {
      data: image.toDataURL(),
      title: source.getTitle() || "Ruang Baca Virtual",
      url: source.webContents.getURL(),
    });
  } catch (err) {
    console.error("Gagal menjepret halaman RBV:", err);
    win.webContents.send("rbv-screenshot-captured", { error: "Halaman RBV gagal dijepret. Coba tekan F9 lagi." });
  } finally {
    setTimeout(() => {
      isCapturingRbv = false;
    }, 250);
  }
}

// ---------- Status login Tuton untuk chip akun di header Asisten ----------
// null berarti belum diketahui, misalnya belum dicek atau jaringan mati
let tutonStatus = null;

function setTutonStatus(status) {
  tutonStatus = status;
  if (win && !win.isDestroyed()) win.webContents.send("tuton-status", status);
}

// Saat aplikasi dibuka jendela Tuton belum tentu terbuka, jadi sesi tersimpan dicek lewat halaman dasbor.
// Moodle mengalihkan ke halaman login jika sesi sudah habis, dan halaman itu tidak punya menu akun.
async function checkTutonLogin() {
  try {
    const res = await session.fromPartition("persist:tuton").fetch(new URL("my/", TUTON_URL).href);
    if (!res.ok) return { loggedIn: false, name: "", nim: "" };
    return parseDashboard(await res.text());
  } catch (err) {
    return null;
  }
}

// Jendela Tuton melapor setiap halaman selesai dimuat. Halaman RBV atau login Microsoft tidak punya menu akun, jadi diabaikan.
ipcMain.on("tuton-status", (event, payload) => {
  if (!tutonWin || event.sender !== tutonWin.webContents || !isTutonUrl(event.senderFrame.url)) return;
  if (!payload || typeof payload !== "object") return;
  if (payload.usertext) setTutonStatus(parseUsertext(payload.usertext));
  else if (payload.onLoginPage) setTutonStatus({ loggedIn: false, name: "", nim: "" });
});

ipcMain.handle("get-tuton-status", async (event) => {
  if (!win || event.sender !== win.webContents) return null;
  if (!tutonStatus) tutonStatus = await checkTutonLogin();
  return tutonStatus;
});

// Keluar berarti menghapus cookie sesi Tuton di aplikasi ini saja. Akun Microsoft di browser lain tidak tersentuh.
ipcMain.handle("tuton-logout", async (event) => {
  if (!win || event.sender !== win.webContents) return null;
  if (tutonWin && !tutonWin.isDestroyed()) tutonWin.close();
  await session.fromPartition("persist:tuton").clearStorageData();
  setTutonStatus({ loggedIn: false, name: "", nim: "" });
  return tutonStatus;
});

ipcMain.on("capture-rbv-page", (event) => {
  if (win && event.sender === win.webContents) captureRbvPage();
});

// Hasil baca halaman hanya diterima dari jendela Tuton yang sedang membuka halaman UT
ipcMain.on("tuton-capture", (event, payload) => {
  if (!tutonWin || event.sender !== tutonWin.webContents || !isTutonUrl(event.senderFrame.url)) return;
  if (!win || win.isDestroyed()) return;
  win.webContents.send("tuton-capture", payload);
  if (win.isMinimized()) win.restore();
  win.focus();
});

// Naskah dari Asisten disusun di kolom jawaban Tuton. Tidak ada yang dikirim ke server Tuton,
// fillAnswer hanya mengisi editor dan pengguna sendiri yang menekan tombol kirim.
const FILL_TIMEOUT_MS = 8000;

ipcMain.handle("fill-tuton", async (event, payload) => {
  if (!win || event.sender !== win.webContents) return { ok: false, message: "Permintaan ditolak." };
  if (!payload || typeof payload.html !== "string" || typeof payload.text !== "string") {
    return { ok: false, message: "Naskah kosong atau rusak." };
  }
  if (!tutonWin || tutonWin.isDestroyed()) {
    return { ok: false, message: "Jendela Tuton belum dibuka. Buka Tuton, masuk ke halaman balas diskusi atau isian tugas, lalu coba lagi." };
  }
  if (!isTutonUrl(tutonWin.webContents.getURL())) {
    return { ok: false, message: "Jendela Tuton sedang tidak membuka halaman UT." };
  }
  const target = tutonWin;
  const args = JSON.stringify({ html: payload.html, text: payload.text, force: Boolean(payload.force) });
  const timeout = new Promise((resolve) => setTimeout(() => resolve(null), FILL_TIMEOUT_MS));
  let result;
  try {
    // Dijalankan di dunia utama halaman supaya bisa memakai API TinyMCE milik Moodle
    result = await Promise.race([target.webContents.executeJavaScript(`(${fillAnswer})(${args})`, true), timeout]);
  } catch (err) {
    console.error("Gagal mengisi kolom jawaban Tuton:", err);
  }
  if (!result || typeof result !== "object") {
    return { ok: false, message: "Kolom jawaban gagal diisi. Tunggu halaman Tuton selesai dimuat lalu coba lagi." };
  }
  if (result.ok && !target.isDestroyed()) {
    if (target.isMinimized()) target.restore();
    target.focus();
    // Fokus keyboard dipindah ke halaman. Tanpa ini ketikan bisa jatuh ke bingkai jendela, Space membuka menu jendela.
    target.webContents.focus();
  }
  return result;
});

ipcMain.on("set-theme", (event, isDark) => {
  const target = BrowserWindow.fromWebContents(event.sender);
  if (!target) return;
  target.setTitleBarOverlay({ color: "#00000000", symbolColor: isDark ? SYMBOL_COLOR.dark : SYMBOL_COLOR.light });
});

async function boot() {
  createWindow();
  try {
    const port = await findFreePort();
    backend = startBackend(port);
    backend.once("error", (err) => showFatal(`Backend gagal dijalankan: ${err.message}`));
    await waitForServer(port);
    win.loadURL(`http://${HOST}:${port}`);
  } catch (err) {
    showFatal(err.message);
  }
}

function showFatal(message) {
  if (!win || win.isDestroyed()) return;
  const page = `<!doctype html><html><body style="margin:0;height:100vh;display:grid;place-items:center;background:#0c0a09;color:#fca5a5;font:500 13px 'Segoe UI',sans-serif;-webkit-app-region:drag;text-align:center;padding:0 24px">${message.replace(/</g, "&lt;")}</body></html>`;
  win.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(page)}`);
}

// Satu aplikasi satu backend. Membuka lagi cukup memunculkan jendela yang sudah ada.
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (!win) return;
    if (win.isMinimized()) win.restore();
    win.focus();
  });
  app.whenReady().then(boot);
}

app.on("window-all-closed", () => app.quit());

// Keluar normal langsung matikan backend. Keluar paksa ditangani pipe stdin di startBackend.
app.on("will-quit", () => {
  if (backend && backend.exitCode === null) backend.kill();
});
