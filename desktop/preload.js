const { contextBridge, ipcRenderer } = require("electron");

// Satu-satunya jembatan halaman web ke proses utama. Tombol jendela sudah native, jadi cukup tema dan Tuton.
contextBridge.exposeInMainWorld("desktop", {
  setTheme: (isDark) => ipcRenderer.send("set-theme", Boolean(isDark)),
  captureRbvPage: () => ipcRenderer.send("capture-rbv-page"),
  fillTuton: (payload) => ipcRenderer.invoke("fill-tuton", payload),
  onTutonCapture: (callback) => ipcRenderer.on("tuton-capture", (_event, payload) => callback(payload)),
  onRbvScreenshot: (callback) => ipcRenderer.on("rbv-screenshot-captured", (_event, payload) => callback(payload)),
});
