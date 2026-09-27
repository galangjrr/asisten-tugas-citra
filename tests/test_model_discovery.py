import os
import pytest
from tools.gemini_client import (
    get_configured_models,
    get_active_models,
    _extract_version_tuple,
    DEFAULT_GENERATION_MODELS,
    DEFAULT_FAST_MODELS,
)


def test_extract_version_tuple():
    assert _extract_version_tuple("gemini-3.8-flash") == [3.0, 8.0]
    assert _extract_version_tuple("gemini-3.6-flash") == [3.0, 6.0]
    assert _extract_version_tuple("gemini-3.1-flash-lite") == [3.0, 1.0]
    assert _extract_version_tuple("gemini-flash-latest") == [0.0]


def test_configured_models_env_override(monkeypatch):
    monkeypatch.setenv("GEMINI_GENERATION_MODELS", "custom-model-1, custom-model-2")
    monkeypatch.setenv("GEMINI_FAST_MODELS", "custom-fast-1")

    gen_models = get_configured_models("generation")
    assert gen_models == ["custom-model-1", "custom-model-2"]

    fast_models = get_configured_models("fast")
    assert fast_models == ["custom-fast-1"]


@pytest.mark.anyio
async def test_get_active_models_env_override(monkeypatch):
    monkeypatch.setenv("GEMINI_GENERATION_MODELS", "env-model-a, env-model-b")
    models = await get_active_models("generation")
    assert models == ["env-model-a", "env-model-b"]


@pytest.mark.anyio
async def test_get_active_models_disabled_auto_fetch(monkeypatch):
    monkeypatch.delenv("GEMINI_GENERATION_MODELS", raising=False)
    monkeypatch.setenv("GEMINI_AUTO_FETCH_MODELS", "false")

    models = await get_active_models("generation")
    assert models == DEFAULT_GENERATION_MODELS


@pytest.mark.anyio
async def test_get_active_models_live_fetch(monkeypatch):
    monkeypatch.delenv("GEMINI_GENERATION_MODELS", raising=False)
    monkeypatch.delenv("GEMINI_FAST_MODELS", raising=False)
    monkeypatch.setenv("GEMINI_AUTO_FETCH_MODELS", "true")

    # Uji pemanggilan ke Google jika API key tersedia
    if os.getenv("GEMINI_API_KEY"):
        models = await get_active_models("generation")
        assert len(models) > 0
        assert all(isinstance(m, str) for m in models)
        # Pastikan tidak ada model tts atau native audio yang bocor
        for m in models:
            assert "tts" not in m
            assert "native-audio" not in m

        fast_models = await get_active_models("fast")
        assert len(fast_models) > 0
