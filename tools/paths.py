import os
import sys

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Exe PyInstaller berjalan dari folder Temp\_MEIxxxx yang dihapus saat aplikasi ditutup,
# jadi tugas, unduhan, dan ekspor disimpan di LocalAppData, satu tempat dengan profil webview.
if getattr(sys, "frozen", False):
    STORAGE_DIR = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "AsistenTugasCitra", "storage")
else:
    STORAGE_DIR = os.path.join(PROJECT_DIR, "storage")
