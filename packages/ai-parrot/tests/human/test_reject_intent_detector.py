"""Unit tests for RejectIntentDetector.

TASK-1278 — FEAT-194 hitl-escalation-tier
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from parrot.human.escalation_intent import RejectIntentDetector


# ---------------------------------------------------------------------------
# Regex hits
# ---------------------------------------------------------------------------

class TestRegexPositives:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("phrase", [
        "pasame con un humano",
        "pasame con humano",
        "necesito un humano",
        "necesito humano",
        "quiero hablar con un humano",
        "escalar",
        "atención humana",
        "atencion humana",
        "ayuda humana",
        "hablar con soporte",
        "esto no me sirve",
        "esto no me ayuda",
        "I need a human",
        "need a human",
        "talk to a human",
        "talk to human",
        "speak with an agent",
        "please escalate",
        "escalate this",
        "let me talk to support",
        "human help",
        "live agent please",
        "live agent",
        "this isn't helping",
        "this isnt helping",
    ])
    async def test_positive(self, phrase: str) -> None:
        d = RejectIntentDetector()
        assert await d.is_escalation_intent(phrase) is True

    @pytest.mark.asyncio
    async def test_case_insensitive(self) -> None:
        d = RejectIntentDetector()
        assert await d.is_escalation_intent("I NEED A HUMAN") is True

    @pytest.mark.asyncio
    async def test_unicode_normalisation(self) -> None:
        """Accented chars are normalised before matching."""
        d = RejectIntentDetector()
        # 'é' normalised to 'e' via NFKD — regex uses [oó] so both work
        assert await d.is_escalation_intent("Atención humana por favor") is True


class TestRegexNegatives:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("phrase", [
        "thanks!",
        "ok",
        "",
        "   ",
        "yes",
        "no",
        "sure thing",
        "what is the weather today?",
    ])
    async def test_negative(self, phrase: str) -> None:
        d = RejectIntentDetector()
        assert await d.is_escalation_intent(phrase) is False

    @pytest.mark.asyncio
    async def test_non_string_returns_false(self) -> None:
        d = RejectIntentDetector()
        assert await d.is_escalation_intent(42) is False  # type: ignore[arg-type]
        assert await d.is_escalation_intent(None) is False  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_custom_phrases_override_defaults(self) -> None:
        """Custom phrase list replaces defaults — default phrases no longer match."""
        d = RejectIntentDetector(regex_phrases=[r"\btest_only\b"])
        assert await d.is_escalation_intent("I need a human") is False
        assert await d.is_escalation_intent("test_only please") is True


# ---------------------------------------------------------------------------
# LLM fallback
# ---------------------------------------------------------------------------

class TestLlmFallback:
    @pytest.mark.asyncio
    async def test_llm_not_called_when_regex_matches(self) -> None:
        """LLM is NOT called if regex already matched."""
        llm = AsyncMock(return_value=True)
        d = RejectIntentDetector(llm_client=llm)
        result = await d.is_escalation_intent("I need a human")
        assert result is True
        llm.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_called_on_ambiguous_short_input(self) -> None:
        """LLM is called for short input that doesn't match regex."""
        llm = AsyncMock(return_value=True)
        d = RejectIntentDetector(llm_client=llm)
        result = await d.is_escalation_intent("help me out")
        assert result is True
        llm.assert_called_once()

    @pytest.mark.asyncio
    async def test_llm_not_called_on_long_input(self) -> None:
        """LLM is NOT called when input > 80 chars (even if no regex match)."""
        llm = AsyncMock(return_value=True)
        d = RejectIntentDetector(llm_client=llm)
        long_text = "a" * 81
        result = await d.is_escalation_intent(long_text)
        assert result is False
        llm.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_returns_false(self) -> None:
        """If LLM says False, detector returns False."""
        llm = AsyncMock(return_value=False)
        d = RejectIntentDetector(llm_client=llm)
        result = await d.is_escalation_intent("help me out")
        assert result is False

    @pytest.mark.asyncio
    async def test_llm_timeout_returns_false(self) -> None:
        """If LLM takes too long, detector returns False without raising."""
        async def slow(*args, **kwargs):
            await asyncio.sleep(5)
            return True

        d = RejectIntentDetector(
            llm_client=AsyncMock(side_effect=slow),
            llm_timeout_seconds=0.05,
        )
        result = await d.is_escalation_intent("help me out")
        assert result is False

    @pytest.mark.asyncio
    async def test_llm_exception_returns_false(self) -> None:
        """If LLM raises any exception, detector returns False without raising."""
        llm = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
        d = RejectIntentDetector(llm_client=llm)
        result = await d.is_escalation_intent("help me out")
        assert result is False

    @pytest.mark.asyncio
    async def test_no_llm_configured_returns_false(self) -> None:
        """No LLM client → False for non-matching input."""
        d = RejectIntentDetector()
        result = await d.is_escalation_intent("hmm")
        assert result is False
