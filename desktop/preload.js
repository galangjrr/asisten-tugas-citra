const { contextBridge, ipcRenderer } = require("electron");

// Satu-satunya jembatan halaman web ke proses utama. Tombol jendela sudah native, jadi cukup tema dan Tuton.
contextBridge.exposeInMainWorld("desktop", {
  setTheme: (isDark) => ipcRenderer.send("set-theme", Boolean(isDark)),
  openTuton: () => ipcRenderer.send("open-tuton"),
  onTutonCapture: (callback) => ipcRenderer.on("tuton-capture", (_event, payload) => callback(payload)),
});
