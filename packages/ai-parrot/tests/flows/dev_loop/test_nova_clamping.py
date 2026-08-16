"""Unit tests for per-model output-token clamping (FEAT-405, TASK-2085)."""

import logging

import pytest
from parrot.flows.dev_loop.models.llm import LLMCodeDispatchProfile
from parrot.flows.dev_loop.models.nova import (
    MODEL_MAX_OUTPUT_TOKENS,
    effective_max_tokens,
)


@pytest.fixture
def logger():
    return logging.getLogger("test-clamp")


class TestClamping:
    def test_map_contains_verified_ceilings(self):
        assert MODEL_MAX_OUTPUT_TOKENS["minimax.minimax-m2.5"] == 8_192
        assert MODEL_MAX_OUTPUT_TOKENS["moonshotai.kimi-k2.5"] == 16_384
        assert MODEL_MAX_OUTPUT_TOKENS["zai.glm-5"] == 131_072
        assert MODEL_MAX_OUTPUT_TOKENS["anthropic.claude-opus-5"] == 131_072

    def test_clamp_minimax_to_8192(self, logger, caplog):
        with caplog.at_level(logging.WARNING):
            assert effective_max_tokens("minimax.minimax-m2.5", 32_768, logger) == 8_192
        assert any("8192" in r.getMessage() for r in caplog.records)

    def test_clamp_kimi_to_16384(self, logger, caplog):
        with caplog.at_level(logging.WARNING):
            assert effective_max_tokens("moonshotai.kimi-k2.5", 32_768, logger) == 16_384
        assert any("16384" in r.getMessage() for r in caplog.records)

    def test_clamp_warning_names_model_requested_effective(self, logger, caplog):
        with caplog.at_level(logging.WARNING):
            effective_max_tokens("minimax.minimax-m2.5", 32_768, logger)
        message = caplog.records[0].getMessage()
        assert "minimax.minimax-m2.5" in message
        assert "32768" in message
        assert "8192" in message

    def test_no_clamp_when_under_ceiling(self, logger, caplog):
        with caplog.at_level(logging.WARNING):
            assert effective_max_tokens("minimax.minimax-m2.5", 4_096, logger) == 4_096
        assert not caplog.records, "happy path must not warn"

    def test_no_clamp_when_at_ceiling(self, logger, caplog):
        with caplog.at_level(logging.WARNING):
            assert effective_max_tokens("minimax.minimax-m2.5", 8_192, logger) == 8_192
        assert not caplog.records

    def test_unknown_model_passes_through(self, logger, caplog):
        with caplog.at_level(logging.WARNING):
            assert effective_max_tokens("some.future-model", 32_768, logger) == 32_768
        assert not caplog.records


class TestProfileBoundUnchanged:
    def test_profile_bound_not_widened(self):
        """The le=32768 bound must survive — clamping replaced widening."""
        field = LLMCodeDispatchProfile.model_fields["max_tokens"]
        assert any(getattr(m, "le", None) == 32_768 for m in field.metadata)
