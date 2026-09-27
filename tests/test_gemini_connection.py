import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
from tools.gemini_client import get_gemini_client


load_dotenv()


def check_gemini_connection():
    """Menguji keaktifan kunci API Gemini dan komunikasi jaringan ke Google AI Studio."""
    try:
        client = get_gemini_client()
        response = client.models.generate_content(
            model="gemini-3.5-flash-lite",
            contents="Jawab dengan satu kata: Aktif"
        )
        print(f"[SUKSES] Koneksi Gemini API terverifikasi: {response.text.strip()}")
        return True
    except Exception as e:
        print(f"[GAGAL] Error saat memanggil Gemini API: {e}")
        return False


if __name__ == "__main__":
    check_gemini_connection()
