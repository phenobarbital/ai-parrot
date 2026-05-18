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
        payload = {"system_prompt": "old"}
        result = client._apply_cache_hints(payload, segments)
        assert isinstance(result.get("system_prompt", ""), str)

    def test_empty_segments_noop(self):
        client = self._make_client()
        payload = {"system_prompt": "original"}
        result = client._apply_cache_hints(payload, [])
        assert result["system_prompt"] == "original"

    def test_segments_concatenated_with_double_newline(self):
        client = self._make_client()
        segments = [
            CacheableSegment(text="first", cacheable=True),
            CacheableSegment(text="second", cacheable=False),
        ]
        payload = {}
        result = client._apply_cache_hints(payload, segments)
        assert result["system_prompt"] == "first\n\nsecond"

    def test_single_segment(self):
        client = self._make_client()
        segments = [CacheableSegment(text="only segment", cacheable=True)]
        payload = {}
        result = client._apply_cache_hints(payload, segments)
        assert result["system_prompt"] == "only segment"

    def test_payload_other_keys_preserved(self):
        client = self._make_client()
        segments = [CacheableSegment(text="text", cacheable=True)]
        payload = {"model": "gpt-4o", "messages": []}
        result = client._apply_cache_hints(payload, segments)
        assert result["model"] == "gpt-4o"
        assert result["messages"] == []
        assert "system_prompt" in result

    def test_non_cacheable_segments_still_included(self):
        client = self._make_client()
        segments = [
            CacheableSegment(text="dynamic", cacheable=False),
            CacheableSegment(text="also dynamic", cacheable=False),
        ]
        payload = {}
        result = client._apply_cache_hints(payload, segments)
        assert "dynamic" in result["system_prompt"]
        assert "also dynamic" in result["system_prompt"]
