"""
Backend lokal untuk shell desktop Electron di folder desktop/.
Electron memilih port kosong lalu menjalankan berkas ini dengan port tersebut sebagai argumen.
Bisa juga dijalankan manual: python run_app.py 8000
"""
import os
import sys
import threading

import uvicorn

HOST = "127.0.0.1"


def exit_when_parent_dies(server: uvicorn.Server):
    """
    Electron memberi stdin berupa pipe yang tidak pernah ditulis. Pipe itu baru tertutup saat
    Electron mati, termasuk dibunuh paksa, jadi baca sampai EOF lalu matikan server dengan rapi.
    """
    stdin = sys.stdin or open(0, closefd=False)
    stdin.read()
    server.should_exit = True


def main():
    args = sys.argv[1:]
    watch_parent = "--exit-with-parent" in args
    ports = [a for a in args if a.isdigit()]
    port = int(ports[0]) if ports else 8000

    # Mode skrip: pindah ke folder proyek supaya .env dan berkas lokal kebaca.
    # Mode exe: Electron sudah mengatur cwd ke folder aplikasi tempat .env disimpan.
    if not getattr(sys, "frozen", False):
        os.chdir(os.path.dirname(os.path.abspath(__file__)))

    # Import setelah chdir supaya load_dotenv baca .env dari folder yang benar
    from api.main import app

    # log_config=None wajib: di mode tanpa console sys.stdout itu None dan formatter bawaan uvicorn bakal crash.
    # Batas 5 detik supaya request Gemini yang masih jalan tidak menahan backend setelah jendela mati.
    server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=port, log_config=None, timeout_graceful_shutdown=5))
    if watch_parent:
        threading.Thread(target=exit_when_parent_dies, args=(server,), daemon=True).start()
    server.run()


if __name__ == "__main__":
    main()
