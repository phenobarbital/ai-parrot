"""Tests for parrot.memory.unified.models."""
import pytest
from pydantic import ValidationError

from parrot.memory.unified.models import MemoryConfig, MemoryContext


# ---------------------------------------------------------------------------
# MemoryContext
# ---------------------------------------------------------------------------

class TestMemoryContext:
    def test_default_values(self):
        ctx = MemoryContext()
        assert ctx.episodic_warnings == ""
        assert ctx.relevant_skills == ""
        assert ctx.conversation_summary == ""
        assert ctx.tokens_used == 0
        assert ctx.tokens_budget == 2000

    def test_to_prompt_string_all_sections(self):
        ctx = MemoryContext(
            episodic_warnings="Don't call API without auth",
            relevant_skills="Use get_schema for DB queries",
            conversation_summary="User asked about weather",
        )
        result = ctx.to_prompt_string()
        assert "<past_failures_to_avoid>" in result
        assert "Don't call API without auth" in result
        assert "</past_failures_to_avoid>" in result
        assert "<relevant_skills>" in result
        assert "Use get_schema for DB queries" in result
        assert "</relevant_skills>" in result
        assert "<recent_conversation>" in result
        assert "User asked about weather" in result
        assert "</recent_conversation>" in result

    def test_to_prompt_string_empty_sections_omitted(self):
        ctx = MemoryContext(episodic_warnings="warning only")
        result = ctx.to_prompt_string()
        assert "<past_failures_to_avoid>" in result
        assert "<relevant_skills>" not in result
        assert "<recent_conversation>" not in result

    def test_to_prompt_string_only_skills(self):
        ctx = MemoryContext(relevant_skills="some skill")
        result = ctx.to_prompt_string()
        assert "<past_failures_to_avoid>" not in result
        assert "<relevant_skills>" in result
        assert "<recent_conversation>" not in result

    def test_to_prompt_string_only_conversation(self):
        ctx = MemoryContext(conversation_summary="hello there")
        result = ctx.to_prompt_string()
        assert "<past_failures_to_avoid>" not in result
        assert "<relevant_skills>" not in result
        assert "<recent_conversation>" in result

    def test_to_prompt_string_all_empty(self):
        ctx = MemoryContext()
        result = ctx.to_prompt_string()
        assert result == ""

    def test_to_prompt_string_sections_separated_by_blank_line(self):
        ctx = MemoryContext(
            episodic_warnings="warn",
            relevant_skills="skill",
        )
        result = ctx.to_prompt_string()
        assert "\n\n" in result

    def test_tokens_used_non_negative(self):
        with pytest.raises(ValidationError):
            MemoryContext(tokens_used=-1)


# ---------------------------------------------------------------------------
# MemoryConfig
# ---------------------------------------------------------------------------

class TestMemoryConfig:
    def test_default_config(self):
        config = MemoryConfig()
        assert config.max_context_tokens == 2000
        assert config.enable_episodic is True
        assert config.enable_skills is True
        assert config.enable_conversation is True
        assert config.episodic_max_warnings == 3
        assert config.skill_max_context == 3
        assert config.skill_auto_extract is False

    def test_default_weights_sum_to_one(self):
        config = MemoryConfig()
        total = config.episodic_weight + config.skill_weight + config.conversation_weight
        assert abs(total - 1.0) < 0.01

    def test_weights_must_sum_to_one(self):
        with pytest.raises(ValidationError, match="Weights must sum to 1.0"):
            MemoryConfig(
                episodic_weight=0.5,
                skill_weight=0.5,
                conversation_weight=0.5,
            )

    def test_valid_custom_weights(self):
        config = MemoryConfig(
            episodic_weight=0.5,
            skill_weight=0.2,
            conversation_weight=0.3,
        )
        assert config.episodic_weight == 0.5

    def test_weights_tolerance(self):
        # 0.33 + 0.33 + 0.34 = 1.00 — should pass
        config = MemoryConfig(
            episodic_weight=0.33,
            skill_weight=0.33,
            conversation_weight=0.34,
        )
        assert config is not None

    def test_weight_out_of_range(self):
        with pytest.raises(ValidationError):
            MemoryConfig(episodic_weight=1.5, skill_weight=0.0, conversation_weight=0.0)

    def test_all_subsystems_disabled(self):
        config = MemoryConfig(
            enable_episodic=False,
            enable_skills=False,
            enable_conversation=False,
        )
        assert not config.enable_episodic

    def test_custom_token_budget(self):
        config = MemoryConfig(max_context_tokens=500)
        assert config.max_context_tokens == 500
