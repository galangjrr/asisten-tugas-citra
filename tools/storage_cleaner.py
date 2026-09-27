import os
import time
from typing import Optional


DEFAULT_STORAGE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "storage")


def clean_storage_by_age(max_age_hours: int = 24, storage_dir: Optional[str] = None) -> int:
    """
    Membersihkan berkas di direktori storage yang telah melewati batas usia tertentu.
    Menjaga berkas sistem seperti .gitkeep agar tidak terhapus.
    """
    target_dir = storage_dir or DEFAULT_STORAGE_DIR
    if not os.path.exists(target_dir):
        return 0

    now = time.time()
    max_age_seconds = max_age_hours * 3600
    deleted_count = 0

    try:
        entries = os.listdir(target_dir)
    except OSError as e:
        print(f"Gagal membaca direktori storage: {e}")
        return 0

    for filename in entries:
        # Jangan hapus berkas gitkeep atau file sistem tersembunyi
        if filename == ".gitkeep" or filename.startswith("."):
            continue

        filepath = os.path.join(target_dir, filename)
        if not os.path.isfile(filepath):
            continue

        try:
            file_mtime = os.path.getmtime(filepath)
            age_seconds = now - file_mtime

            if age_seconds > max_age_seconds:
                os.remove(filepath)
                deleted_count += 1
                print(f"Berkas kadaluarsa dibersihkan: {filename} (Usia: {age_seconds / 3600:.1f} jam)")
        except OSError as e:
            # Cegah crash jika ada berkas yang sedang dikunci sistem operasi
            print(f"Gagal menghapus berkas {filename}: {e}")
            continue

    return deleted_count
