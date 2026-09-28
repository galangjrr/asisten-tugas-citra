import os
import re
import time
import asyncio
from typing import Any, Dict, List, Optional
from google import genai
from dotenv import load_dotenv


load_dotenv()

DEFAULT_GENERATION_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.6-flash",
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash-lite",
    "gemini-flash-latest"
]

DEFAULT_FAST_MODELS = [
    "gemini-3.1-flash-lite",
    "gemini-3.6-flash",
    "gemini-3.8-flash",
    "gemini-flash-lite-latest"
]

_cached_generation_models: List[str] = []
_cached_fast_models: List[str] = []
_last_fetch_time: float = 0.0
CACHE_TTL_SECONDS: float = 3600.0

# Model yang terbukti tidak bisa dipakai akun ini (404 atau kuota 0) dilewati sampai aplikasi ditutup.
# ponytail: hanya di memori, jadi tiap aplikasi dibuka ulang model mati dicoba sekali lagi. Simpan ke berkas jika itu terasa lambat.
_dead_models: set = set()
# Model yang kena rate limit biasa, dilewati sampai waktu jeda habis
_cooldown_until: Dict[str, float] = {}
TRANSIENT_RETRY_DELAY: float = 2.0


def get_gemini_client() -> genai.Client:
    """Menginisialisasi klien Gemini dengan API Key dari environment variable."""
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        raise ValueError("GEMINI_API_KEY belum disetel di berkas .env")
    return genai.Client(api_key=api_key)


def _extract_version_tuple(name: str) -> List[float]:
    """Mengekstrak nomor versi numerik dari nama model untuk pengurutan prioritas."""
    match = re.search(r"gemini-(\d+(?:\.\d+)?)", name)
    if match:
        try:
            return [float(p) for p in match.group(1).split(".")]
        except ValueError:
            pass
    return [0.0]


def get_configured_models(category: str = "generation") -> List[str]:
    """
    Mengambil daftar model berdasarkan konfigurasi environment atau cache memori.
    Fallback ke daftar bawaan jika belum ada tarikan dari Google.
    """
    env_var = "GEMINI_GENERATION_MODELS" if category == "generation" else "GEMINI_FAST_MODELS"
    custom_models = os.getenv(env_var, "").strip()
    if custom_models:
        return [m.strip() for m in custom_models.split(",") if m.strip()]

    global _cached_generation_models, _cached_fast_models
    if category == "generation" and _cached_generation_models:
        return list(_cached_generation_models)
    if category == "fast" and _cached_fast_models:
        return list(_cached_fast_models)

    return list(DEFAULT_GENERATION_MODELS if category == "generation" else DEFAULT_FAST_MODELS)


async def get_active_models(category: str = "generation") -> List[str]:
    """
    Mengambil daftar model aktif secara dinamis langsung dari server Google GenAI.
    Menyaring model yang sudah discontinue dan hanya menyisakan model teks yang siap pakai.
    """
    # 1. Cek override di .env terlebih dahulu
    env_var = "GEMINI_GENERATION_MODELS" if category == "generation" else "GEMINI_FAST_MODELS"
    custom_models = os.getenv(env_var, "").strip()
    if custom_models:
        return [m.strip() for m in custom_models.split(",") if m.strip()]

    # 2. Cek apakah fitur auto fetch dinonaktifkan
    auto_fetch = os.getenv("GEMINI_AUTO_FETCH_MODELS", "true").lower() in ("true", "1", "yes")
    if not auto_fetch:
        return list(DEFAULT_GENERATION_MODELS if category == "generation" else DEFAULT_FAST_MODELS)

    # 3. Cek cache in-memory
    global _cached_generation_models, _cached_fast_models, _last_fetch_time
    now = time.time()
    if _cached_generation_models and (now - _last_fetch_time < CACHE_TTL_SECONDS):
        return list(_cached_generation_models if category == "generation" else _cached_fast_models)

    # 4. Tarik daftar model resmi dari Google
    try:
        client = get_gemini_client()
        pager = await asyncio.wait_for(client.aio.models.list(), timeout=5.0)
        live_candidates: List[str] = []
        async for m in pager:
            actions = getattr(m, "supported_actions", []) or getattr(m, "supported_generation_methods", [])
            if "generateContent" not in actions:
                continue
            clean_name = m.name.removeprefix("models/")
            # Singkirkan model non-teks atau eksperimental yang tidak stabil
            if any(bad in clean_name for bad in ["tts", "native-audio", "image", "live-preview"]):
                continue
            live_candidates.append(clean_name)

        if live_candidates:
            flash_models = [m for m in live_candidates if "flash" in m]
            generation_sorted = sorted(
                flash_models,
                key=_extract_version_tuple,
                reverse=True
            )
            for alias in ["gemini-flash-latest"]:
                if alias in live_candidates and alias not in generation_sorted:
                    generation_sorted.append(alias)

            lite_models = [m for m in generation_sorted if "lite" in m]
            regular_models = [m for m in generation_sorted if "lite" not in m]
            fast_sorted = lite_models + regular_models

            _cached_generation_models = generation_sorted
            _cached_fast_models = fast_sorted
            _last_fetch_time = now

            return list(_cached_generation_models if category == "generation" else _cached_fast_models)
    except Exception as e:
        print(f"Peringatan: Gagal menarik daftar model langsung dari Google: {e}. Menggunakan cadangan.")

    return list(DEFAULT_GENERATION_MODELS if category == "generation" else DEFAULT_FAST_MODELS)


def classify_model_error(error: Exception) -> str:
    """Mengelompokkan error Gemini: 'dead' tidak akan pernah jalan, 'cooldown' kena limit sementara, 'transient' server penuh."""
    code = getattr(error, "code", None)
    text = str(error)
    if code == 404 or "NOT_FOUND" in text or "no longer available" in text:
        return "dead"
    if code == 429 or "RESOURCE_EXHAUSTED" in text:
        # Kuota free tier bernilai 0 berarti model memang tertutup untuk akun ini
        return "dead" if re.search(r"limit:\s*0\b", text) else "cooldown"
    return "transient"


def _retry_after_seconds(error: Exception, default: float = 60.0) -> float:
    match = re.search(r"retry in ([\d.]+)s", str(error))
    return float(match.group(1)) if match else default


async def generate_with_fallback(
    category: str,
    contents: Any,
    config: Any = None,
    timeout: float = 30.0,
    total_budget: float = 90.0,
) -> Any:
    """
    Memanggil generate_content dengan rantai model cadangan.
    Model mati diingat dan dilewati, model yang kena limit dijeda, dan model yang sedang penuh dicoba ulang satu kali.
    Mengembalikan respons pertama yang berisi teks, atau melempar RuntimeError berisi error terakhir.
    """
    client = get_gemini_client()
    models = await get_active_models(category)
    deadline = time.monotonic() + total_budget
    last_error: Optional[Exception] = None

    for attempt in range(2):
        retry_models: List[str] = []
        for model_name in models:
            if model_name in _dead_models or _cooldown_until.get(model_name, 0) > time.time():
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 1:
                raise RuntimeError(f"Batas waktu seluruh model Gemini habis: {last_error}")
            try:
                response = await asyncio.wait_for(
                    client.aio.models.generate_content(model=model_name, contents=contents, config=config),
                    timeout=min(timeout, remaining),
                )
                if response and response.text and response.text.strip():
                    return response
                last_error = RuntimeError(f"{model_name} mengembalikan respons kosong")
                retry_models.append(model_name)
            except Exception as e:
                last_error = e
                kind = "transient" if isinstance(e, asyncio.TimeoutError) else classify_model_error(e)
                if kind == "dead":
                    _dead_models.add(model_name)
                elif kind == "cooldown":
                    _cooldown_until[model_name] = time.time() + _retry_after_seconds(e)
                else:
                    retry_models.append(model_name)
                print(f"Peringatan: model {model_name} gagal ({kind}): {str(e)[:160]}")

        if not retry_models or attempt == 1:
            break
        # Server penuh biasanya cuma sesaat, jadi model yang tadi penuh dicoba sekali lagi
        await asyncio.sleep(TRANSIENT_RETRY_DELAY)
        models = retry_models

    raise RuntimeError(f"Seluruh model Gemini sedang tidak tersedia: {last_error}")
