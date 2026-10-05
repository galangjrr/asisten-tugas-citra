"""
Backend lokal untuk shell desktop Electron di folder desktop/.
Electron memilih port kosong lalu menjalankan berkas ini dengan port tersebut sebagai argumen.
Bisa juga dijalankan manual: python run_app.py 8000
"""
import os
import sys

import uvicorn

HOST = "127.0.0.1"


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000

    # Mode skrip: pindah ke folder proyek supaya .env dan berkas lokal kebaca.
    # Mode exe: Electron sudah mengatur cwd ke folder aplikasi tempat .env disimpan.
    if not getattr(sys, "frozen", False):
        os.chdir(os.path.dirname(os.path.abspath(__file__)))

    # Import setelah chdir supaya load_dotenv baca .env dari folder yang benar
    from api.main import app

    # log_config=None wajib: di mode tanpa console sys.stdout itu None dan formatter bawaan uvicorn bakal crash
    uvicorn.run(app, host=HOST, port=port, log_config=None)


if __name__ == "__main__":
    main()
