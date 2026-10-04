import os
import sys
import time
import socket
import threading
import ctypes
import ctypes.wintypes

import uvicorn
import webview

APP_TITLE = "Asisten Tugas Citra"
HOST = "127.0.0.1"
# Lebar konten max-w-5xl 1024px + scrollbar 10px + ruang tepi. Jendela tanpa bingkai, jadi tidak ada frame yang dihitung.
WINDOW_WIDTH = 1050

# Garis tepi jendela disamakan dengan border header UI: stone-200 dan dark stone-800
WINDOW_BORDER = {False: "#e7e5e4", True: "#292524"}
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_BORDER_COLOR = 34
DWMWCP_ROUND = 2

def hex_to_colorref(hex_color: str) -> ctypes.c_uint:
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return ctypes.c_uint(r | (g << 8) | (b << 16))


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.wintypes.DWORD),
        ("rcMonitor", ctypes.wintypes.RECT),
        ("rcWork", ctypes.wintypes.RECT),
        ("dwFlags", ctypes.wintypes.DWORD),
    ]


def work_area(hwnd: int) -> tuple:
    """Area kerja monitor tempat jendela berada, di luar taskbar, dalam piksel logis (left, top, width, height)."""
    user32 = ctypes.windll.user32
    user32.MonitorFromWindow.restype = ctypes.c_void_p
    user32.MonitorFromWindow.argtypes = [ctypes.c_void_p, ctypes.wintypes.DWORD]
    monitor = user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    user32.GetMonitorInfoW(ctypes.c_void_p(monitor), ctypes.byref(info))
    scale = user32.GetDpiForWindow(hwnd) / 96
    r = info.rcWork
    return int(r.left / scale), int(r.top / scale), int((r.right - r.left) / scale), int((r.bottom - r.top) / scale)


class DesktopApi:
    """Dipanggil dari JS lewat window.pywebview.api saat tema berganti."""

    def __init__(self):
        self._window = None
        self._maximized = False
        self._restore_bounds = None

    def set_titlebar(self, is_dark: bool):
        """Jendela tanpa bingkai tetap dapat sudut bulat dan garis tepi tipis ala Windows 11 sesuai tema."""
        if not sys.platform.startswith("win") or not self._window or not self._window.native:
            return
        hwnd = self._window.native.Handle.ToInt32()
        dwm = ctypes.windll.dwmapi
        # Atribut sudut dan warna tepi hanya berlaku di Windows 11, di Windows 10 diabaikan tanpa error
        dwm.DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(ctypes.c_int(int(bool(is_dark)))), 4)
        dwm.DwmSetWindowAttribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(ctypes.c_int(DWMWCP_ROUND)), 4)
        dwm.DwmSetWindowAttribute(hwnd, DWMWA_BORDER_COLOR, ctypes.byref(hex_to_colorref(WINDOW_BORDER[bool(is_dark)])), 4)

    def minimize(self):
        self._window.minimize()

    def toggle_maximize(self) -> bool:
        """
        Besarkan ke area kerja monitor secara manual. Maximize bawaan jendela tanpa bingkai menutupi taskbar.
        Mengembalikan status baru supaya ikon tombol di UI bisa ikut berganti.
        """
        w = self._window
        if self._maximized:
            x, y, width, height = self._restore_bounds
            w.resize(width, height)
            w.move(x, y)
        else:
            self._restore_bounds = (w.x, w.y, w.width, w.height)
            left, top, width, height = work_area(w.native.Handle.ToInt32())
            w.move(left, top)
            w.resize(width, height)
        self._maximized = not self._maximized
        return self._maximized

    def close(self):
        self._window.destroy()

    def fit_height(self, content_height: int):
        """Tinggi jendela ngikutin tinggi halaman, mentok di tinggi layar di luar taskbar."""
        if not sys.platform.startswith("win") or not self._window or not self._window.native:
            return
        _, top, _, max_height = work_area(self._window.native.Handle.ToInt32())
        height = min(int(content_height), max_height)
        self._window.resize(WINDOW_WIDTH, height)
        self._window.move(self._window.x, top + (max_height - height) // 2)


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


def wait_for_server(port: int, timeout: float = 15.0) -> bool:
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            with socket.create_connection((HOST, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def main():
    # Saat dibungkus PyInstaller, __file__ ada di folder temp, jadi pakai folder exe biar .env kebaca
    if getattr(sys, "frozen", False):
        project_dir = os.path.dirname(sys.executable)
    else:
        project_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(project_dir)

    # Import setelah chdir supaya load_dotenv baca .env dari folder yang benar
    from api.main import app

    port = find_free_port()
    # log_config=None wajib: di mode tanpa console sys.stdout itu None dan formatter bawaan uvicorn bakal crash
    server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=port, log_config=None))
    threading.Thread(target=server.run, daemon=True).start()

    if not wait_for_server(port):
        raise RuntimeError("Server lokal gagal menyala")

    webview.settings["ALLOW_DOWNLOADS"] = True
    api = DesktopApi()
    api._window = webview.create_window(
        APP_TITLE,
        f"http://{HOST}:{port}",
        js_api=api,
        width=WINDOW_WIDTH,
        height=820,
        min_size=(900, 600),
        background_color="#0c0a09",
        text_select=True,
        # Header aplikasi jadi title bar. Geser hanya lewat area .pywebview-drag-region, bukan seluruh halaman.
        # ponytail: jendela tanpa bingkai tidak bisa ditarik dari tepinya, ukuran diatur fit_height dan tombol besarkan.
        # Kalau perlu tarik tepi, tangani WM_NCHITTEST di jendela WinForms.
        frameless=True,
        easy_drag=False,
        shadow=True,
    )
    # Profil WebView disimpan permanen supaya localStorage seperti nama dan NIM tetap ingat di sesi berikutnya
    storage = os.path.join(os.environ.get("LOCALAPPDATA", project_dir), "AsistenTugasCitra", "webview")
    webview.start(private_mode=False, storage_path=storage)

    # Jendela ditutup, server ikut berhenti
    server.should_exit = True


if __name__ == "__main__":
    main()
