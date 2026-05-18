"""Unit tests for AgentContextLoader and AGENT_CONTEXT_LAYER.

FEAT-181 — Provider-Agnostic Prompt Caching (TASK-1219).
"""
import time
import pytest
from pathlib import Path
from unittest.mock import patch
from parrot.bots.prompts.agent_context import load_agent_context, AGENT_CONTEXT_LAYER, _read_cached
from parrot.bots.prompts.layers import RenderPhase


class TestLoadAgentContext:
    def setup_method(self):
        """Clear lru_cache before each test for isolation."""
        _read_cached.cache_clear()

    def test_reads_existing_file(self, tmp_path):
        ctx_file = tmp_path / "my_agent.md"
        ctx_file.write_text("# Agent Context\nSome content here.")
        with patch("parrot.bots.prompts.agent_context.AGENT_CONTEXT_DIR", tmp_path):
            _read_cached.cache_clear()
            result = load_agent_context("my_agent")
        assert "Some content here" in result

    def test_missing_file_returns_empty(self, tmp_path):
        with patch("parrot.bots.prompts.agent_context.AGENT_CONTEXT_DIR", tmp_path):
            result = load_agent_context("nonexistent")
        assert result == ""

    def test_missing_file_returns_empty_string_type(self, tmp_path):
        with patch("parrot.bots.prompts.agent_context.AGENT_CONTEXT_DIR", tmp_path):
            result = load_agent_context("ghost_agent")
        assert isinstance(result, str)
        assert result == ""

    def test_mtime_invalidation(self, tmp_path):
        ctx_file = tmp_path / "bot.md"
        ctx_file.write_text("version1")
        with patch("parrot.bots.prompts.agent_context.AGENT_CONTEXT_DIR", tmp_path):
            _read_cached.cache_clear()
            v1 = load_agent_context("bot")
            assert v1 == "version1"
            # Simulate file update (change content + mtime)
            time.sleep(0.05)
            ctx_file.write_text("version2")
            v2 = load_agent_context("bot")
            assert v2 == "version2"

    def test_caching_returns_same_for_same_mtime(self, tmp_path):
        ctx_file = tmp_path / "cached_bot.md"
        ctx_file.write_text("cached_content")
        with patch("parrot.bots.prompts.agent_context.AGENT_CONTEXT_DIR", tmp_path):
            _read_cached.cache_clear()
            v1 = load_agent_context("cached_bot")
            v2 = load_agent_context("cached_bot")
        assert v1 == v2 == "cached_content"

    def test_read_cached_directly(self, tmp_path):
        """Test _read_cached helper directly."""
        _read_cached.cache_clear()
        test_file = tmp_path / "test.md"
        test_file.write_text("hello")
        mtime = test_file.stat().st_mtime
        result = _read_cached(str(test_file), mtime)
        assert result == "hello"


class TestAgentContextLayer:
    def test_is_configure_phase(self):
        assert AGENT_CONTEXT_LAYER.phase == RenderPhase.CONFIGURE

    def test_is_cacheable(self):
        assert AGENT_CONTEXT_LAYER.cacheable is True

    def test_priority_between_identity_and_pre_instructions(self):
        # IDENTITY = 10, PRE_INSTRUCTIONS = 15 — must be between them
        assert 10 < AGENT_CONTEXT_LAYER.priority < 15

    def test_priority_is_12(self):
        assert AGENT_CONTEXT_LAYER.priority == 12

    def test_name(self):
        assert AGENT_CONTEXT_LAYER.name == "agent_context"

    def test_renders_with_content(self):
        result = AGENT_CONTEXT_LAYER.render({"agent_context_content": "ctx data"})
        assert result is not None
        assert "ctx data" in result

    def test_skips_when_empty_string(self):
        result = AGENT_CONTEXT_LAYER.render({"agent_context_content": ""})
        assert result is None

    def test_skips_when_whitespace_only(self):
        result = AGENT_CONTEXT_LAYER.render({"agent_context_content": "   "})
        assert result is None

    def test_skips_when_key_missing(self):
        result = AGENT_CONTEXT_LAYER.render({})
        assert result is None

    def test_wraps_in_agent_context_tags(self):
        result = AGENT_CONTEXT_LAYER.render({"agent_context_content": "my context"})
        assert "<agent_context>" in result
        assert "</agent_context>" in result

    def test_importable_from_package(self):
        from parrot.bots.prompts import AGENT_CONTEXT_LAYER as ACL
        assert ACL is AGENT_CONTEXT_LAYER
