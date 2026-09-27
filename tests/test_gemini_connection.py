import os
from dotenv import load_dotenv
from google import genai


load_dotenv()


def check_gemini_connection():
    """Menguji keaktifan kunci API Gemini dan komunikasi jaringan ke Google AI Studio."""
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key or len(api_key) < 10:
        print("[GAGAL] GEMINI_API_KEY belum disetel di file .env")
        return False

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-flash-latest",
            contents="Jawab dengan satu kata: Aktif"
        )
        print(f"[SUKSES] Koneksi Gemini API terverifikasi: {response.text.strip()}")
        return True
    except Exception as e:
        print(f"[GAGAL] Error saat memanggil Gemini API: {e}")
        return False


if __name__ == "__main__":
    check_gemini_connection()
