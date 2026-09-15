"""Gemini via Google's OpenAI-compatible endpoint (FEAT-549, spec §3 M3).

Template: ``parrot.clients.amazon.nova.mantle.BedrockMantleClient``. Everything
(completions, tool calling, retry) is inherited from ``OpenAIBaseClient``; this
module only resolves endpoint + key. It deliberately declares NO
``_default_model`` / ``_fallback_model`` / ``_lightweight_model``.
"""
from __future__ import annotations

from navconfig import config  # verified in use: google/client.py:189

from ..openai_base import OpenAIBaseClient  # verified: parrot/clients/openai_base.py:66

GEMINI_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


class GeminiOpenAICompatClient(OpenAIBaseClient):
    """OpenAI-SDK-shaped client for Gemini models.

    Args:
        api_key: Explicit key; falls back to ``GEMINI_API_KEY`` then ``GOOGLE_API_KEY`` (navconfig).
        base_url: Defaults to :data:`GEMINI_OPENAI_BASE_URL`.
        **kwargs: Forwarded to ``OpenAIBaseClient`` (``model``, ``temperature``, ``max_tokens`` …).

    Raises:
        ValueError: When no API key resolves.
    """

    def __init__(self, api_key: str | None = None, base_url: str | None = None, **kwargs) -> None:
        resolved_key = api_key or config.get("GEMINI_API_KEY") or config.get("GOOGLE_API_KEY")
        if not resolved_key:
            raise ValueError(
                "GeminiOpenAICompatClient needs an API key: pass api_key= or set "
                "GEMINI_API_KEY / GOOGLE_API_KEY"
            )
        super().__init__(api_key=resolved_key, base_url=base_url or GEMINI_OPENAI_BASE_URL, **kwargs)
        self.api_key = resolved_key  # mantle.py:128 — re-set after super().__init__
        self.base_headers = {  # mantle.py:139-142 — keep headers in sync with the key
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
