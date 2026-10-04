import os
import json
from typing import Dict, Any, Optional

from tools.paths import STORAGE_DIR
TASKS_DIR = os.path.join(STORAGE_DIR, "tasks")


def get_tasks_dir() -> str:
    """Mengembalikan direktori penyimpanan berkas JSON tugas dan memastikan foldernya ada."""
    os.makedirs(TASKS_DIR, exist_ok=True)
    return TASKS_DIR


import re


def sanitize_task_id(task_id: str) -> str:
    """Membersihkan ID tugas dari karakter berbahaya untuk mencegah celah path traversal."""
    return re.sub(r"[^a-zA-Z0-9_\-]", "", str(task_id or "")).strip()


def save_task_to_disk(task_id: str, task: Dict[str, Any]) -> str:
    """
    Menyimpan data tugas lengkap ke berkas JSON lokal secara atomik.
    Membuat draf tugas tetap utuh dan tahan terhadap interupsi listrik atau crash mendadak.
    """
    clean_id = sanitize_task_id(task_id)
    if not clean_id or not isinstance(task, dict):
        return ""

    target_dir = get_tasks_dir()
    filepath = os.path.join(target_dir, f"{clean_id}.json")
    temp_filepath = os.path.join(target_dir, f"{clean_id}.tmp")

    try:
        # Tulis ke berkas sementara terlebih dahulu
        with open(temp_filepath, "w", encoding="utf-8") as f:
            json.dump(task, f, ensure_ascii=False, indent=2)
        # Ganti berkas target secara atomik agar tidak ada kondisi berkas setengah tertulis
        os.replace(temp_filepath, filepath)
        return filepath
    except Exception as e:
        print(f"Peringatan: Gagal menyimpan tugas {clean_id} ke disk: {e}")
        if os.path.exists(temp_filepath):
            try:
                os.remove(temp_filepath)
            except OSError:
                pass
        return ""


def load_task_from_disk(task_id: str) -> Optional[Dict[str, Any]]:
    """
    Membaca data tugas dari berkas JSON lokal jika tidak ada di memori RAM.
    """
    clean_id = sanitize_task_id(task_id)
    if not clean_id:
        return None

    filepath = os.path.join(TASKS_DIR, f"{clean_id}.json")
    if not os.path.exists(filepath):
        return None

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception as e:
        print(f"Peringatan: Gagal membaca berkas tugas {filepath}: {e}")

    return None
