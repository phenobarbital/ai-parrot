"""Unit tests for GoogleGenAIClient cache translator.

FEAT-181 — Provider-Agnostic Prompt Caching (TASK-1224).

Updated to reflect the concurrency-safe design where _apply_cache_hints()
returns (payload, pending_segments) instead of storing state on self.
"""
import logging
import pytest
from unittest.mock import MagicMock, AsyncMock
from parrot.bots.prompts.segments import CacheableSegment
from parrot.clients.google.client import GoogleGenAIClient


class TestGeminiCacheTranslator:
    def _make_client(self):
        """Create a bare GoogleGenAIClient instance without full init."""
        client = GoogleGenAIClient.__new__(GoogleGenAIClient)
        client.logger = logging.getLogger("test")
        return client

    def test_min_cache_tokens(self):
        assert GoogleGenAIClient._min_cache_tokens == 4096

    def test_below_threshold_skips(self):
        """Short segments skip caching without error."""
        client = self._make_client()
        segments = [CacheableSegment(text="short", cacheable=True)]
        payload = {}
        result_payload, pending = client._apply_cache_hints(payload, segments)
        # Should not have cached_content in payload
        assert "cached_content" not in result_payload

    def test_below_threshold_pending_segments_none(self):
        """When below threshold, pending_segments is None."""
        client = self._make_client()
        segments = [CacheableSegment(text="short", cacheable=True)]
        _, pending = client._apply_cache_hints({}, segments)
        assert pending is None

    def test_above_threshold_returns_segments(self):
        """Long segments are returned as pending_segments for async creation."""
        client = self._make_client()
        long_text = "x" * 20000  # ~5000 tokens, above 4096 threshold
        segments = [CacheableSegment(text=long_text, cacheable=True)]
        payload = {}
        _, pending = client._apply_cache_hints(payload, segments)
        # Segments should be returned for async create
        assert pending is not None
        assert pending is segments

    def test_empty_segments_noop(self):
        """Empty segments list: payload unchanged, no error."""
        client = self._make_client()
        payload = {"system_prompt": "original"}
        result_payload, pending = client._apply_cache_hints(payload, [])
        assert result_payload == payload
        assert pending is None

    def test_non_cacheable_segments_below_threshold(self):
        """Non-cacheable-only segments (even if long) skip caching."""
        client = self._make_client()
        long_text = "x" * 20000
        segments = [CacheableSegment(text=long_text, cacheable=False)]
        _, pending = client._apply_cache_hints({}, segments)
        # cacheable_text is empty → 0 tokens → below threshold
        assert pending is None

    def test_estimate_tokens(self):
        """Token estimation: 4 chars ≈ 1 token."""
        client = self._make_client()
        assert client._estimate_tokens("x" * 4000) == 1000
        assert client._estimate_tokens("") == 0
        assert client._estimate_tokens("hello") == 1  # 5//4 == 1

    def test_payload_keys_preserved_below_threshold(self):
        """Payload keys are untouched when caching is skipped."""
        client = self._make_client()
        payload = {"model": "gemini-2.5-flash", "contents": []}
        segments = [CacheableSegment(text="hi", cacheable=True)]
        result_payload, _ = client._apply_cache_hints(payload, segments)
        assert result_payload["model"] == "gemini-2.5-flash"
        assert result_payload["contents"] == []

    def test_cache_ttl_default(self):
        """Default TTL is 300s."""
        assert GoogleGenAIClient._cache_ttl == "300s"

    @pytest.mark.asyncio
    async def test_maybe_apply_gemini_cache_noop_when_no_pending(self):
        """_maybe_apply_gemini_cache is a no-op when segments is None."""
        client = self._make_client()
        payload = {"contents": []}
        mock_genai_client = MagicMock()
        result = await client._maybe_apply_gemini_cache(
            mock_genai_client, "gemini-2.5-flash", payload, None
        )
        assert result == payload
        # aio.caches.create should NOT have been called
        mock_genai_client.aio.caches.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_maybe_apply_gemini_cache_creates_cached_content(self):
        """_maybe_apply_gemini_cache calls caches.create and injects cached_content."""
        client = self._make_client()
        long_text = "x" * 20000
        pending_segments = [
            CacheableSegment(text=long_text, cacheable=True)
        ]

        mock_cached = MagicMock()
        mock_cached.name = "cachedContents/abc123"

        mock_caches = MagicMock()
        mock_caches.create = AsyncMock(return_value=mock_cached)

        mock_aio = MagicMock()
        mock_aio.caches = mock_caches

        mock_genai_client = MagicMock()
        mock_genai_client.aio = mock_aio

        payload = {"contents": []}
        result = await client._maybe_apply_gemini_cache(
            mock_genai_client, "gemini-2.5-flash", payload, pending_segments
        )
        assert result["cached_content"] == "cachedContents/abc123"
        mock_caches.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_maybe_apply_gemini_cache_fail_open(self):
        """When CachedContent creation fails, payload is returned unchanged."""
        client = self._make_client()
        long_text = "x" * 20000
        pending_segments = [
            CacheableSegment(text=long_text, cacheable=True)
        ]

        mock_caches = MagicMock()
        mock_caches.create = AsyncMock(side_effect=RuntimeError("API error"))

        mock_aio = MagicMock()
        mock_aio.caches = mock_caches

        mock_genai_client = MagicMock()
        mock_genai_client.aio = mock_aio

        payload = {"contents": []}
        result = await client._maybe_apply_gemini_cache(
            mock_genai_client, "gemini-2.5-flash", payload, pending_segments
        )
        # Should NOT have cached_content — fail-open
        assert "cached_content" not in result
