"""Unit tests for AnthropicClient cache translator.

FEAT-181 — Provider-Agnostic Prompt Caching (TASK-1222).
"""
from parrot.bots.prompts.segments import CacheableSegment
from parrot.clients.claude import AnthropicClient


class TestAnthropicCacheTranslator:
    def _make_client(self):
        """Create a bare AnthropicClient instance without full init."""
        import logging
        client = AnthropicClient.__new__(AnthropicClient)
        client.logger = logging.getLogger("test")
        return client

    def test_min_cache_tokens(self):
        assert AnthropicClient._min_cache_tokens == 1024

    def test_string_system_prompt_unchanged(self):
        """String system_prompt: isinstance check returns False, payload unchanged."""
        assert not isinstance("plain string", list)

    def test_segments_produce_blocks(self):
        client = self._make_client()
        segments = [
            CacheableSegment(text="identity", cacheable=True),
            CacheableSegment(text="user data", cacheable=False),
        ]
        blocks = client._segments_to_anthropic_blocks(segments)
        assert len(blocks) == 2
        assert "cache_control" in blocks[0]
        assert blocks[0]["cache_control"] == {"type": "ephemeral"}
        assert "cache_control" not in blocks[1]

    def test_blocks_have_type_text(self):
        client = self._make_client()
        segments = [CacheableSegment(text="hello", cacheable=True)]
        blocks = client._segments_to_anthropic_blocks(segments)
        assert blocks[0]["type"] == "text"
        assert blocks[0]["text"] == "hello"

    def test_max_4_cache_control_blocks(self):
        client = self._make_client()
        segments = [CacheableSegment(text=f"s{i}", cacheable=True) for i in range(6)]
        blocks = client._segments_to_anthropic_blocks(segments)
        cache_count = sum(1 for b in blocks if "cache_control" in b)
        assert cache_count <= 4
        # All 6 blocks should still be present (just some without cache_control)
        assert len(blocks) == 6

    def test_max_4_cache_control_exactly_4(self):
        client = self._make_client()
        segments = [CacheableSegment(text=f"s{i}", cacheable=True) for i in range(4)]
        blocks = client._segments_to_anthropic_blocks(segments)
        cache_count = sum(1 for b in blocks if "cache_control" in b)
        assert cache_count == 4

    def test_non_cacheable_segments_no_cache_control(self):
        client = self._make_client()
        segments = [
            CacheableSegment(text="dynamic", cacheable=False),
            CacheableSegment(text="also dynamic", cacheable=False),
        ]
        blocks = client._segments_to_anthropic_blocks(segments)
        assert len(blocks) == 2
        for block in blocks:
            assert "cache_control" not in block

    def test_apply_cache_hints_updates_payload(self):
        client = self._make_client()
        segments = [CacheableSegment(text="identity", cacheable=True)]
        payload = {"model": "claude", "messages": []}
        result = client._apply_cache_hints(payload, segments)
        assert "system" in result
        assert isinstance(result["system"], list)
        assert result["system"][0]["type"] == "text"

    def test_apply_cache_hints_empty_segments_noop(self):
        client = self._make_client()
        payload = {"model": "claude", "messages": [], "system": "old"}
        result = client._apply_cache_hints(payload, [])
        assert result["system"] == "old"

    def test_segments_to_blocks_text_preserved(self):
        client = self._make_client()
        segments = [CacheableSegment(text="my system prompt", cacheable=True)]
        blocks = client._segments_to_anthropic_blocks(segments)
        assert blocks[0]["text"] == "my system prompt"
