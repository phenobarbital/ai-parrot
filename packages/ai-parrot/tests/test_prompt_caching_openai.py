"""Unit tests for OpenAIClient cache translator.

FEAT-181 — Provider-Agnostic Prompt Caching (TASK-1223).
"""
from parrot.bots.prompts.segments import CacheableSegment
from parrot.clients.gpt import OpenAIClient


class TestOpenAICacheTranslator:
    def _make_client(self):
        """Create a bare OpenAIClient instance without full init."""
        import logging
        client = OpenAIClient.__new__(OpenAIClient)
        client.logger = logging.getLogger("test")
        return client

    def test_min_cache_tokens(self):
        assert OpenAIClient._min_cache_tokens == 1024

    def test_segments_produce_string(self):
        client = self._make_client()
        segments = [
            CacheableSegment(text="identity text", cacheable=True),
            CacheableSegment(text="user data", cacheable=False),
        ]
        payload = {}
        result = client._apply_cache_hints(payload, segments)
        # OpenAI uses "system" key (valid OpenAI API field), not "system_prompt"
        assert isinstance(result.get("system", ""), str)

    def test_empty_segments_noop(self):
        client = self._make_client()
        payload = {"model": "gpt-4o"}
        result = client._apply_cache_hints(payload, [])
        # No segments → payload unchanged (no "system" key added)
        assert "system" not in result
        assert result["model"] == "gpt-4o"

    def test_segments_concatenated_with_double_newline(self):
        client = self._make_client()
        segments = [
            CacheableSegment(text="first", cacheable=True),
            CacheableSegment(text="second", cacheable=False),
        ]
        payload = {}
        result = client._apply_cache_hints(payload, segments)
        # Combined under "system" (the valid OpenAI messages API field)
        assert result["system"] == "first\n\nsecond"

    def test_single_segment(self):
        client = self._make_client()
        segments = [CacheableSegment(text="only segment", cacheable=True)]
        payload = {}
        result = client._apply_cache_hints(payload, segments)
        assert result["system"] == "only segment"

    def test_payload_other_keys_preserved(self):
        client = self._make_client()
        segments = [CacheableSegment(text="text", cacheable=True)]
        payload = {"model": "gpt-4o", "messages": []}
        result = client._apply_cache_hints(payload, segments)
        assert result["model"] == "gpt-4o"
        assert result["messages"] == []
        # Combined text stored under the valid "system" key
        assert "system" in result

    def test_non_cacheable_segments_still_included(self):
        client = self._make_client()
        segments = [
            CacheableSegment(text="dynamic", cacheable=False),
            CacheableSegment(text="also dynamic", cacheable=False),
        ]
        payload = {}
        result = client._apply_cache_hints(payload, segments)
        # All segments are collapsed into the combined string, regardless of cacheability
        assert "dynamic" in result["system"]
        assert "also dynamic" in result["system"]
