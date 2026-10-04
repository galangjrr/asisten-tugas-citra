from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def _fake_response(text, uris):
    chunks = [SimpleNamespace(web=SimpleNamespace(uri=u, title=f"Sumber {i}")) for i, u in enumerate(uris)]
    meta = SimpleNamespace(grounding_chunks=chunks)
    return SimpleNamespace(text=text, candidates=[SimpleNamespace(grounding_metadata=meta)])


def _patch(monkeypatch, text, uris):
    import tools.publication_lookup as pl
    captured = {}

    async def fake_generate(category, contents, config=None, **kwargs):
        captured["config"], captured["prompt"] = config, contents
        return _fake_response(text, uris)

    monkeypatch.setattr(pl, "generate_with_fallback", fake_generate)
    return pl, captured


@pytest.mark.anyio
async def test_lookup_uses_google_search_and_returns_sources(monkeypatch):
    text = '```json\n{"author": "Willa Cather", "year": "1896", "venue": "The Home Monthly", "note": "Terbit pertama di The Home Monthly, Desember 1896."}\n```'
    pl, captured = _patch(monkeypatch, text, ["https://a.example/cather", "https://a.example/cather", "https://b.example"])
    result = await pl.lookup_publication("A Burglar's Christmas", "Willa Cather")

    assert captured["config"].tools[0].google_search is not None
    assert "PERTAMA" in captured["prompt"] and "A Burglar's Christmas" in captured["prompt"]
    assert result["found"] is True
    assert (result["author"], result["year"], result["venue"]) == ("Willa Cather", 1896, "The Home Monthly")
    # Sumber kembar cukup ditampilkan sekali
    assert [s["uri"] for s in result["sources"]] == ["https://a.example/cather", "https://b.example"]


@pytest.mark.anyio
async def test_lookup_without_web_sources_is_not_trusted(monkeypatch):
    # Model menjawab tanpa membuka web: tahunnya bisa karangan, jadi tidak boleh mengisi kolom
    pl, _ = _patch(monkeypatch, '{"author": "Willa Cather", "year": 1902, "venue": "x", "note": "tebakan"}', [])
    result = await pl.lookup_publication("A Burglar's Christmas")
    assert result["found"] is False
    assert result["year"] is None and result["author"] is None


@pytest.mark.anyio
async def test_lookup_drops_impossible_year_and_null_text(monkeypatch):
    pl, _ = _patch(monkeypatch, '{"author": "null", "year": 3020, "venue": "Gramedia", "note": ""}', ["https://c.example"])
    result = await pl.lookup_publication("Robohnya Surau Kami")
    assert result["year"] is None and result["author"] is None
    assert result["venue"] == "Gramedia" and result["found"] is True


def test_lookup_endpoint_reports_quota_and_validates_title(monkeypatch):
    import api.routes as routes

    async def busy(title, author=""):
        raise RuntimeError("429 RESOURCE_EXHAUSTED")

    monkeypatch.setattr(routes, "lookup_publication", busy)
    res = client.post("/api/lookup-publication", json={"title": "A Burglar's Christmas"})
    assert res.status_code == 503 and "kuota" in res.json()["detail"]
    assert client.post("/api/lookup-publication", json={"title": "ab"}).status_code == 422

    async def ok(title, author=""):
        return {"found": True, "author": "Willa Cather", "year": 1896, "venue": "The Home Monthly", "note": "n", "sources": [{"title": "t", "uri": "https://x"}]}

    monkeypatch.setattr(routes, "lookup_publication", ok)
    data = client.post("/api/lookup-publication", json={"title": "A Burglar's Christmas", "author": "Willa Cather"}).json()
    assert data["year"] == 1896 and data["sources"][0]["uri"] == "https://x"
