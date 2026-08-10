"""A caller-supplied API key must survive construction.

Both SDKs fall back to a process-wide environment variable when no key reaches
them, so losing a caller's key produces a *working* client authenticated as
somebody else — no exception, no warning. Multi-tenant callers that pass one
key per tenant depend on this not happening.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def platform_keys(monkeypatch):
    """Environment keys that must never win over an explicit argument."""
    monkeypatch.setenv("GOOGLE_API_KEY", "AIza-FROM-ENVIRONMENT")
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-FROM-ENVIRONMENT")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-FROM-ENVIRONMENT")


def test_google_keeps_the_explicit_key():
    """``GoogleGenAIClient`` pops ``api_key`` before delegating upwards.

    The base class must not then blank the attribute, because ``get_client()``
    reads it back to build ``genai.Client(api_key=...)``.
    """
    from parrot.clients.google.client import GoogleGenAIClient

    client = GoogleGenAIClient(model="gemini-2.5-flash", api_key="AIza-EXPLICIT")

    assert client.api_key == "AIza-EXPLICIT"


def test_google_still_falls_back_to_the_environment():
    """Omitting the argument keeps the documented environment fallback."""
    from parrot.clients.google.client import GoogleGenAIClient

    client = GoogleGenAIClient(model="gemini-2.5-flash")

    assert client.api_key == "AIza-FROM-ENVIRONMENT"


def test_anthropic_keeps_the_explicit_key():
    """The Anthropic key must reach the transport and the auth header."""
    from parrot.clients.claude import AnthropicClient

    client = AnthropicClient(model="claude-sonnet-4-6", api_key="sk-ant-EXPLICIT")

    assert client._backend.api_key == "sk-ant-EXPLICIT"
    assert client.base_headers["x-api-key"] == "sk-ant-EXPLICIT"
    assert client.api_key == "sk-ant-EXPLICIT"
