const { contextBridge, ipcRenderer } = require("electron");

// Satu-satunya jembatan halaman web ke proses utama. Tombol jendela sudah native, jadi cuma tema yang perlu dikirim.
contextBridge.exposeInMainWorld("desktop", {
  setTheme: (isDark) => ipcRenderer.send("set-theme", Boolean(isDark)),
});
