import pytest

from parrot.clients.google import GEMINI_OPENAI_BASE_URL, GeminiOpenAICompatClient
from parrot.clients.google import openai_compat as mod


def test_compat_client_key_resolution(monkeypatch):
    monkeypatch.setattr(mod.config, "get", lambda k, *a, **kw: {"GEMINI_API_KEY": "gk"}.get(k))
    c = GeminiOpenAICompatClient()
    assert c.api_key == "gk" and c.base_headers["Authorization"] == "Bearer gk"
    monkeypatch.setattr(mod.config, "get", lambda k, *a, **kw: {"GOOGLE_API_KEY": "ok"}.get(k))
    assert GeminiOpenAICompatClient().api_key == "ok"
    monkeypatch.setattr(mod.config, "get", lambda k, *a, **kw: None)
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        GeminiOpenAICompatClient()


def test_compat_client_default_base_url():
    c = GeminiOpenAICompatClient(api_key="k")
    assert c.base_url == GEMINI_OPENAI_BASE_URL


def test_compat_client_explicit_base_url_wins():
    c = GeminiOpenAICompatClient(api_key="k", base_url="https://example.test/")
    assert c.base_url == "https://example.test/"


def test_compat_client_has_no_model_defaults():
    for name in ("_default_model", "_fallback_model", "_lightweight_model"):
        assert name not in GeminiOpenAICompatClient.__dict__
