"""Tests for parrot.memory.unified.models."""
import pytest
from pydantic import ValidationError

from parrot.memory.agent_memory.models import MemoryRequestScope
from parrot.memory.unified.models import MemoryCandidate, MemoryConfig, MemoryContext


def _scope(*, user_id: str | None = None) -> MemoryRequestScope:
    """Build a deterministic trusted scope for candidate tests."""
    return MemoryRequestScope(
        tenant_id="tenant-1",
        agent_id="agent-1",
        user_id=user_id,
        turn_id="turn-1",
        identity_provenance="runtime_derived",
    )


# ---------------------------------------------------------------------------
# MemoryContext
# ---------------------------------------------------------------------------

class TestMemoryContext:
    def test_default_values(self):
        ctx = MemoryContext()
        assert ctx.episodic_warnings == ""
        assert ctx.relevant_skills == ""
        assert ctx.conversation_summary == ""
        assert ctx.user_knowledge == ""
        assert ctx.delivered_refs == ()
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

    def test_user_knowledge_is_contextual_section(self):
        """User knowledge is rendered as a separate contextual section."""
        ctx = MemoryContext(user_knowledge="The user prefers dark mode.")

        result = ctx.to_prompt_string()

        assert "<user_knowledge>" in result
        assert "The user prefers dark mode." in result
        assert "<system>" not in result

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

    def test_normalized_section_weights_include_only_enabled_capabilities(self):
        config = MemoryConfig(
            enable_episodic=False,
            enable_skills=False,
            enable_conversation=True,
            enable_user_memory=True,
            conversation_weight=0.4,
            user_weight=0.2,
        )

        weights = config.normalized_section_weights

        assert set(weights) == {"conversation", "user_knowledge"}
        assert weights["conversation"] == pytest.approx(2 / 3)
        assert weights["user_knowledge"] == pytest.approx(1 / 3)


class TestMemoryCandidate:
    def test_scope_and_bounded_similarity_are_preserved(self):
        candidate = MemoryCandidate(
            scope=_scope(user_id="user-1"),
            memory_id="memory-1",
            content_version="v1",
            source="episodic",
            text="Use the authenticated endpoint.",
            relevance=0.8,
            similarity=0.75,
            ranking_score=0.6,
            provenance="retrieved",
        )

        assert candidate.relevance == 0.8
        assert candidate.similarity == 0.75
        assert candidate.ranking_score == 0.6
        assert candidate.dynamics_state_ref is None

        with pytest.raises(ValidationError):
            MemoryCandidate(
                scope=_scope(),
                memory_id="memory-2",
                content_version="v1",
                source="episodic",
                text="out of range",
                relevance=1.1,
            )

    def test_user_candidate_cannot_carry_dynamics_state(self):
        with pytest.raises(ValidationError, match="cannot carry an experiential dynamics state"):
            MemoryCandidate(
                scope=_scope(user_id="user-1"),
                memory_id="profile-1",
                content_version="v1",
                source="user",
                text="The user prefers dark mode.",
                relevance=0.9,
                candidate_type="user",
                dynamics_state_ref="state-1",
            )

        candidate = MemoryCandidate(
            scope=_scope(user_id="user-1"),
            memory_id="profile-1",
            content_version="v1",
            source="user",
            text="The user prefers dark mode.",
            relevance=0.9,
            candidate_type="user",
        )
        assert not hasattr(candidate, "grade")
