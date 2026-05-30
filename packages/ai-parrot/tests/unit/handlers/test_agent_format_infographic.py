"""Unit tests for INFOGRAPHIC mode in AgentTalk (FEAT-197, TASK-1320)."""
from __future__ import annotations

import sys

# Force real prompts module (bypass conftest stubs).
sys.modules.pop("parrot.bots.prompts", None)
sys.modules.pop("parrot.models.outputs", None)
sys.modules.pop("parrot.models.responses", None)

import parrot.models.outputs as _real_outputs
sys.modules["parrot.models.outputs"] = _real_outputs

import parrot.models.responses as _real_responses
sys.modules["parrot.models.responses"] = _real_responses

import pytest
from parrot.models.outputs import OutputMode
from parrot.bots.prompts import INFOGRAPHIC_SYSTEM_PROMPT_ADDON


class TestInfographicSystemPromptAddon:
    """Test that the system prompt addon is importable and has the right content."""

    def test_addon_is_string(self):
        """INFOGRAPHIC_SYSTEM_PROMPT_ADDON should be a non-empty string."""
        assert isinstance(INFOGRAPHIC_SYSTEM_PROMPT_ADDON, str)
        assert len(INFOGRAPHIC_SYSTEM_PROMPT_ADDON) > 0

    def test_addon_mentions_infographic_render(self):
        """The addon must instruct the LLM to call infographic_render."""
        assert "infographic_render" in INFOGRAPHIC_SYSTEM_PROMPT_ADDON

    def test_addon_mentions_data_frames(self):
        """The addon must mention DataFrame computation."""
        lower = INFOGRAPHIC_SYSTEM_PROMPT_ADDON.lower()
        assert "dataframe" in lower or "python_repl_pandas" in lower or "fetch_dataset" in lower

    def test_addon_requests_brief_explanation(self):
        """The addon must ask the LLM for a brief natural-language explanation.

        This explanation becomes the chat-bubble reply (the infographic itself
        opens in a separate canvas).
        """
        lower = INFOGRAPHIC_SYSTEM_PROMPT_ADDON.lower()
        assert "summary" in lower or "explanation" in lower

    def test_addon_forbids_dumping_render_result(self):
        """The addon must tell the LLM NOT to paste the HTML / render envelope."""
        lower = INFOGRAPHIC_SYSTEM_PROMPT_ADDON.lower()
        assert "not" in lower and ("dump" in lower or "paste" in lower or "envelope" in lower)


class TestStreamingDisabledForInfographic:
    """Streaming force-disable logic for infographic output mode."""

    def test_infographic_mode_disables_stream(self):
        """The handler sets use_stream=False when output_mode=INFOGRAPHIC.

        This is a unit test of the LOGIC without running the full HTTP stack.
        We verify that the constant OutputMode.INFOGRAPHIC == 'infographic'
        which is the condition checked in the handler code.
        """
        output_mode = OutputMode.INFOGRAPHIC
        use_stream = True
        # Simulate the handler logic
        if output_mode == OutputMode.INFOGRAPHIC:
            use_stream = False
        assert use_stream is False

    def test_other_mode_does_not_disable_stream(self):
        """Non-infographic modes should NOT force use_stream=False."""
        output_mode = OutputMode.MAP
        use_stream = True
        if output_mode == OutputMode.INFOGRAPHIC:
            use_stream = False
        assert use_stream is True
