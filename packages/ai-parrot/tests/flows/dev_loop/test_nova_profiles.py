"""Unit tests for the Nova dispatch profiles (FEAT-405, TASK-2084)."""

import pytest
from parrot.flows.dev_loop.models import (
    NovaAdversarialReviewProfile,
    NovaCodeDispatchProfile,
    NovaMechanicalProfile,
)
from parrot.flows.dev_loop.models.nova import NOVA_DEFAULT_CONVERSE_MODEL


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
    def test_default_model_is_native_nova(self):
        assert NovaAdversarialReviewProfile().model == NOVA_DEFAULT_CONVERSE_MODEL

    @pytest.mark.parametrize("forbidden", ["tools", "allowed_commands", "sandbox", "subagent"])
    def test_exposes_no_tool_configuration(self, forbidden):
        """Read-only by construction — the profile cannot carry tools."""
        assert forbidden not in NovaAdversarialReviewProfile.model_fields

    def test_has_diff_truncation_bound(self):
        assert NovaAdversarialReviewProfile().max_diff_chars > 0

    def test_default_review_scope_is_uncommitted(self):
        assert NovaAdversarialReviewProfile().review_scope == "uncommitted"


class TestNovaMechanicalProfile:
    def test_default_model_is_native_nova(self):
        assert NovaMechanicalProfile().model == NOVA_DEFAULT_CONVERSE_MODEL

    def test_output_is_short(self):
        assert NovaMechanicalProfile().max_tokens <= 8192

    @pytest.mark.parametrize("forbidden", ["tools", "allowed_commands", "sandbox", "subagent"])
    def test_exposes_no_tool_configuration(self, forbidden):
        assert forbidden not in NovaMechanicalProfile.model_fields


class TestNovaDefaultConverseModel:
    """Both no-tools Converse seats must default to a *native Amazon Nova*
    id, never to ``us.anthropic.*``.

    Bedrock gates every Anthropic model behind a per-account "Anthropic use
    case details" form; an account with a valid Bedrock API key still gets
    ``ResourceNotFoundException`` until that form is filled in. A Nova
    backend must not need a separate Anthropic entitlement to work at all.
    """

    def test_default_is_an_amazon_nova_id(self):
        assert NOVA_DEFAULT_CONVERSE_MODEL.startswith("us.amazon.nova-")
        assert "anthropic" not in NOVA_DEFAULT_CONVERSE_MODEL

    def test_default_carries_required_geo_prefix(self):
        """Nova 2 Lite has NO in-region access — the ``us.`` inference-profile
        prefix is mandatory (spec ``novaclient-amazon-aws`` Verified AWS Facts).
        """
        assert NOVA_DEFAULT_CONVERSE_MODEL.startswith("us.")

    def test_default_is_not_an_eol_model(self):
        """Nova Premier is Legacy on Bedrock with EOL 2026-09-14 — it must
        never become a default any seat silently depends on."""
        assert "premier" not in NOVA_DEFAULT_CONVERSE_MODEL

    @pytest.mark.parametrize(
        "conf_key",
        ["DEV_LOOP_NOVA_REVIEW_MODEL", "DEV_LOOP_NOVA_MECHANICAL_MODEL"],
    )
    def test_conf_fallbacks_match_the_constant(self, conf_key):
        """``conf.py`` cannot import ``parrot.flows`` (it is foundational and
        imported almost everywhere), so it duplicates the literal. Pin the two
        copies equal here so they cannot drift silently."""
        import os

        from parrot import conf

        if os.environ.get(conf_key):
            pytest.skip(f"{conf_key} is overridden in this environment")
        assert getattr(conf, conf_key) == NOVA_DEFAULT_CONVERSE_MODEL
