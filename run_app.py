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
# Lebar konten header max-w-5xl 1024px + scrollbar 10px + frame jendela 16px
WINDOW_WIDTH = 1050
# Tinggi title bar + frame bawah, hasil ukur outer 820 vs innerHeight 781
WINDOW_CHROME_HEIGHT = 39

# Warna title bar disamain dengan header UI: bg-white dan dark:bg-stone-900
TITLEBAR_THEMES = {
    False: {"caption": "#ffffff", "text": "#1c1917"},
    True: {"caption": "#1c1917", "text": "#f5f5f4"},
}


def hex_to_colorref(hex_color: str) -> ctypes.c_uint:
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return ctypes.c_uint(r | (g << 8) | (b << 16))


class DesktopApi:
    """Dipanggil dari JS lewat window.pywebview.api saat tema berganti."""

    def __init__(self):
        self._window = None

    def set_titlebar(self, is_dark: bool):
        if not sys.platform.startswith("win") or not self._window or not self._window.native:
            return
        hwnd = self._window.native.Handle.ToInt32()
        dwm = ctypes.windll.dwmapi
        theme = TITLEBAR_THEMES[bool(is_dark)]
        # 20 dark mode, 35 warna caption, 36 warna teks, 34 warna border. Caption dan teks cuma jalan di Windows 11
        dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(ctypes.c_int(int(bool(is_dark)))), 4)
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(hex_to_colorref(theme["caption"])), 4)
        dwm.DwmSetWindowAttribute(hwnd, 36, ctypes.byref(hex_to_colorref(theme["text"])), 4)
        dwm.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(hex_to_colorref(theme["caption"])), 4)

    def fit_height(self, content_height: int):
        """Tinggi jendela ngikutin tinggi halaman, mentok di tinggi layar di luar taskbar."""
        if not sys.platform.startswith("win") or not self._window or not self._window.native:
            return
        work_area = ctypes.wintypes.RECT()
        ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(work_area), 0)  # SPI_GETWORKAREA
        scale = ctypes.windll.user32.GetDpiForWindow(self._window.native.Handle.ToInt32()) / 96
        max_height = int((work_area.bottom - work_area.top) / scale)
        height = min(int(content_height) + WINDOW_CHROME_HEIGHT, max_height)
        self._window.resize(WINDOW_WIDTH, height)
        self._window.move(self._window.x, int(work_area.top / scale) + (max_height - height) // 2)


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
    )
    webview.start()

    # Jendela ditutup, server ikut berhenti
    server.should_exit = True


if __name__ == "__main__":
    main()
