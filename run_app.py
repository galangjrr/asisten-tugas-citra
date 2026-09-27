import os
import sys
import time
import socket
import subprocess
import threading
import webbrowser
import uvicorn


def is_port_in_use(host: str = "127.0.0.1", port: int = 8000) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except (OSError, ConnectionRefusedError):
        return False


def wait_for_server(host: str = "127.0.0.1", port: int = 8000, timeout: float = 10.0) -> bool:
    start_time = time.time()
    while time.time() - start_time < timeout:
        if is_port_in_use(host, port):
            return True
        time.sleep(0.2)
    return False


def launch_app_window():
    if not wait_for_server():
        return

    url = "http://127.0.0.1:8000"

    edge_candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]

    for edge_path in edge_candidates:
        if os.path.exists(edge_path):
            try:
                subprocess.Popen([edge_path, f"--app={url}"])
                return
            except Exception:
                pass

    webbrowser.open(url)


def main():
    project_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(project_dir)

    print("=" * 60)
    print("  ASISTEN TUGAS CITRA - MAKALAH KILAT")
    print("  Mode Desktop Satu Klik Anti Ribet")
    print("=" * 60)

    # Jika server sudah aktif sebelumnya
    if is_port_in_use():
        print("  Server lokal sudah aktif di http://127.0.0.1:8000")
        print("  Membuka jendela aplikasi...")
        launch_app_window()
        return

    # Jika server belum aktif, nyalakan server lalu buka jendela aplikasi
    launcher_thread = threading.Thread(target=launch_app_window, daemon=True)
    launcher_thread.start()

    print("  Menyalakan server lokal di http://127.0.0.1:8000...")
    print("  Tutup jendela aplikasi atau tekan Ctrl+C di terminal untuk keluar.")
    print("=" * 60)

    uvicorn.run("api.main:app", host="127.0.0.1", port=8000, log_level="warning")


if __name__ == "__main__":
    main()
