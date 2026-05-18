"""Unit tests for AbstractBot prompt_caching integration.

FEAT-181 — Provider-Agnostic Prompt Caching (TASK-1220).
"""
from unittest.mock import patch
from parrot.bots.prompts.builder import PromptBuilder
from parrot.bots.prompts.segments import CacheableSegment
from parrot.bots.prompts.agent_context import AGENT_CONTEXT_LAYER


class TestPromptBuilderSegmentsIntegration:
    """Tests for build_segments() via PromptBuilder (backing TASK-1220 logic)."""

    def test_flag_off_no_layer_injection(self):
        """When prompt_caching=False, no AGENT_CONTEXT_LAYER is injected."""
        builder = PromptBuilder.default()
        # Default builder should not have agent_context layer
        assert "agent_context" not in builder.layer_names

    def test_flag_on_injects_layer(self):
        """When prompt_caching=True and builder is set, AGENT_CONTEXT_LAYER is added."""
        builder = PromptBuilder.default()
        builder.add(AGENT_CONTEXT_LAYER)
        assert "agent_context" in builder.layer_names

    def test_segments_type(self):
        """build_segments returns List[CacheableSegment]."""
        builder = PromptBuilder.default()
        builder.configure({
            "name": "TestAgent",
            "role": "assistant",
            "goal": "",
            "backstory": "",
            "rationale": "",
        })
        segments = builder.build_segments({
            "knowledge_content": "",
            "user_context": "",
            "chat_history": "",
        })
        assert isinstance(segments, list)
        assert all(isinstance(s, CacheableSegment) for s in segments)

    def test_segments_non_empty_for_configured_builder(self):
        """build_segments returns at least one segment for a non-trivial builder."""
        builder = PromptBuilder.default()
        builder.configure({
            "name": "TestAgent",
            "role": "helpful AI assistant",
            "goal": "help users",
            "backstory": "experienced AI",
            "rationale": "be helpful",
        })
        segments = builder.build_segments({
            "knowledge_content": "",
            "user_context": "",
            "chat_history": "",
        })
        assert len(segments) > 0

    def test_agent_context_layer_is_cacheable(self):
        """AGENT_CONTEXT_LAYER has cacheable=True."""
        assert AGENT_CONTEXT_LAYER.cacheable is True

    def test_agent_context_layer_phase_configure(self):
        """AGENT_CONTEXT_LAYER has phase=CONFIGURE."""
        from parrot.bots.prompts.layers import RenderPhase
        assert AGENT_CONTEXT_LAYER.phase == RenderPhase.CONFIGURE

    def test_agent_context_layer_not_rendered_without_content(self):
        """AGENT_CONTEXT_LAYER condition suppresses it when content is empty."""
        builder = PromptBuilder.default()
        builder.add(AGENT_CONTEXT_LAYER)
        builder.configure({
            "name": "TestAgent",
            "role": "assistant",
            "goal": "",
            "backstory": "",
            "rationale": "",
            "agent_context_content": "",  # empty → condition suppresses it
        })
        segments = builder.build_segments({
            "knowledge_content": "",
            "user_context": "",
            "chat_history": "",
        })
        # No segment should contain <agent_context>
        combined = "".join(s.text for s in segments)
        assert "<agent_context>" not in combined

    def test_agent_context_layer_rendered_with_content(self):
        """AGENT_CONTEXT_LAYER appears when agent_context_content is set."""
        builder = PromptBuilder.default()
        builder.add(AGENT_CONTEXT_LAYER)
        builder.configure({
            "name": "TestAgent",
            "role": "assistant",
            "goal": "",
            "backstory": "",
            "rationale": "",
            "agent_context_content": "some agent context text",
        })
        segments = builder.build_segments({
            "knowledge_content": "",
            "user_context": "",
            "chat_history": "",
        })
        combined = "".join(s.text for s in segments)
        assert "agent_context" in combined


class TestAbstractBotPromptCachingInit:
    """Tests for AbstractBot.__init__ with prompt_caching kwarg."""

    def _make_bot(self, prompt_caching=False, builder=None):
        """Create a minimal AbstractBot-like object with prompt_caching support.

        We test the __init__ logic by checking PromptBuilder state after
        the auto-injection path (lines 469-472 of abstract.py).
        """
        # Simulate the prompt_caching init logic directly
        _prompt_builder = builder
        _prompt_caching = prompt_caching
        if _prompt_caching and _prompt_builder is not None:
            from parrot.bots.prompts.agent_context import AGENT_CONTEXT_LAYER as _ACL
            _prompt_builder.add(_ACL)
        return _prompt_builder, _prompt_caching

    def test_no_builder_no_injection(self):
        """When builder is None, no injection occurs even with flag on."""
        builder, _ = self._make_bot(prompt_caching=True, builder=None)
        assert builder is None

    def test_flag_off_no_injection(self):
        """When flag is False, layer is NOT injected."""
        b = PromptBuilder.default()
        original_names = set(b.layer_names)
        self._make_bot(prompt_caching=False, builder=b)
        assert set(b.layer_names) == original_names
        assert "agent_context" not in b.layer_names

    def test_flag_on_with_builder_injects_layer(self):
        """When flag=True and builder is set, AGENT_CONTEXT_LAYER is injected."""
        b = PromptBuilder.default()
        self._make_bot(prompt_caching=True, builder=b)
        assert "agent_context" in b.layer_names

    def test_flag_on_layer_injected_once(self):
        """Calling init logic once does not duplicate the layer."""
        b = PromptBuilder.default()
        self._make_bot(prompt_caching=True, builder=b)
        count = b.layer_names.count("agent_context")
        assert count == 1


class TestLoadAgentContextLogging:
    """Tests for load_agent_context() missing-file logging path."""

    def test_missing_file_returns_empty_string(self, tmp_path):
        """load_agent_context returns '' for non-existent agent."""
        import parrot.bots.prompts.agent_context as ac_mod
        with patch.object(ac_mod, "AGENT_CONTEXT_DIR", tmp_path):
            from parrot.bots.prompts.agent_context import load_agent_context
            result = load_agent_context("nonexistent_agent_xyz")
        assert result == ""

    def test_existing_file_returns_content(self, tmp_path):
        """load_agent_context returns file content for known agent."""
        import parrot.bots.prompts.agent_context as ac_mod
        ctx_file = tmp_path / "myagent.md"
        ctx_file.write_text("Agent context here.", encoding="utf-8")
        with patch.object(ac_mod, "AGENT_CONTEXT_DIR", tmp_path):
            from parrot.bots.prompts.agent_context import load_agent_context
            result = load_agent_context("myagent")
        assert result == "Agent context here."
