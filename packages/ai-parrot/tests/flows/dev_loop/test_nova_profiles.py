"""Unit tests for the Nova dispatch profiles (FEAT-405, TASK-2084)."""

import pytest
from parrot.flows.dev_loop.models import (
    NovaAdversarialReviewProfile,
    NovaCodeDispatchProfile,
    NovaMechanicalProfile,
)


class TestNovaCodeDispatchProfile:
    def test_default_model_is_minimax(self):
        assert NovaCodeDispatchProfile().model == "minimax.minimax-m2.5"

    def test_default_llm_matches_default_model(self):
        assert NovaCodeDispatchProfile().llm == "nova:minimax.minimax-m2.5"

    def test_llm_derived_from_model(self):
        p = NovaCodeDispatchProfile(model="moonshotai.kimi-k2.5")
        assert p.llm == "nova:moonshotai.kimi-k2.5"

    def test_explicit_llm_not_overwritten(self):
        p = NovaCodeDispatchProfile(model="minimax.minimax-m2.5", llm="nova:custom")
        assert p.llm == "nova:custom"

    def test_max_tokens_within_inherited_bound(self):
        with pytest.raises(ValueError):
            NovaCodeDispatchProfile(max_tokens=99_999)


class TestNovaAdversarialReviewProfile:
    def test_default_model_is_opus5(self):
        assert NovaAdversarialReviewProfile().model == "us.anthropic.claude-opus-5"

    @pytest.mark.parametrize("forbidden", ["tools", "allowed_commands", "sandbox", "subagent"])
    def test_exposes_no_tool_configuration(self, forbidden):
        """Read-only by construction — the profile cannot carry tools."""
        assert forbidden not in NovaAdversarialReviewProfile.model_fields

    def test_has_diff_truncation_bound(self):
        assert NovaAdversarialReviewProfile().max_diff_chars > 0

    def test_default_review_scope_is_uncommitted(self):
        assert NovaAdversarialReviewProfile().review_scope == "uncommitted"


class TestNovaMechanicalProfile:
    def test_default_model_is_haiku(self):
        assert "haiku" in NovaMechanicalProfile().model

    def test_output_is_short(self):
        assert NovaMechanicalProfile().max_tokens <= 8192

    @pytest.mark.parametrize("forbidden", ["tools", "allowed_commands", "sandbox", "subagent"])
    def test_exposes_no_tool_configuration(self, forbidden):
        assert forbidden not in NovaMechanicalProfile.model_fields
