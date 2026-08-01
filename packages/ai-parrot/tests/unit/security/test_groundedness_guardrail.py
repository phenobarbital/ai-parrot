"""Unit tests for `parrot.security.groundedness.guardrail.GroundednessGuardrail`
(FEAT-398, TASK-2044).

Covers the FLAG-only invariant (never TRANSFORM/BLOCK), the non-fatal
scoring-exception contract, and telemetry hygiene (score + counts only,
never atom raw values) — spec §4 test matrix, Module 3.
"""
import logging

import pytest

from parrot.bots.guardrails.base import (
    GuardrailAction,
    GuardrailContext,
    GuardrailStage,
)
from parrot.models.basic import ToolCall
from parrot.models.responses import AIMessage, CompletionUsage
from parrot.security.groundedness.guardrail import GroundednessGuardrail
from parrot.security.groundedness.policy import GroundednessPolicy


def _ai_message(tool_calls: list[ToolCall] | None = None, user_prompt: str = "q") -> AIMessage:
    return AIMessage(
        input=user_prompt,
        output="ignored-by-guardrail",
        model="m",
        provider="p",
        usage=CompletionUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
        tool_calls=tool_calls or [],
    )


def _ctx(ai_message: AIMessage | None = None) -> GuardrailContext:
    extras = {"ai_message": ai_message} if ai_message is not None else {}
    return GuardrailContext(
        stage=GuardrailStage.OUTPUT,
        agent_name="TestBot",
        extras=extras,
    )


def _tool_call(result: str) -> ToolCall:
    return ToolCall(id="1", name="lookup", arguments={}, result=result)


class TestFlagOnlyInvariant:
    @pytest.mark.asyncio
    async def test_flag_only_never_transforms_or_blocks(self):
        guardrail = GroundednessGuardrail()
        ai_message = _ai_message(
            tool_calls=[_tool_call("Revenue was $1,243,500 this quarter.")],
        )
        content = "Revenue reached $1,243,500."

        result = await guardrail.check(content, _ctx(ai_message))

        assert result.action == GuardrailAction.FLAG
        assert result.content is None
        assert result.reason is None
        assert result.report is not None
        assert result.report["score"] == 1.0

    @pytest.mark.asyncio
    async def test_no_ai_message_in_extras_degrades_to_no_evidence(self):
        """Missing ctx.extras['ai_message'] is tolerated — treated as a turn
        with no tool evidence, not an error."""
        guardrail = GroundednessGuardrail()

        result = await guardrail.check("Some answer.", _ctx(ai_message=None))

        assert result.action == GuardrailAction.FLAG
        assert result.report["no_evidence"] is True
        assert result.report["score"] == 1.0


class TestNonFatalScoringContract:
    @pytest.mark.asyncio
    async def test_scorer_exception_degrades_to_pass(self, monkeypatch):
        guardrail = GroundednessGuardrail()

        def _boom(*args, **kwargs):
            raise RuntimeError("scoring blew up")

        monkeypatch.setattr(guardrail.scorer, "score", _boom)
        ai_message = _ai_message(tool_calls=[_tool_call("evidence text")])

        result = await guardrail.check("Some answer.", _ctx(ai_message))

        assert result.action == GuardrailAction.PASS
        assert result.report is None

    @pytest.mark.asyncio
    async def test_evidence_build_exception_degrades_to_pass(self, monkeypatch):
        """Non-fatal contract also covers exceptions raised while building
        the EvidenceIndex (not just the scorer.score() call itself)."""
        guardrail = GroundednessGuardrail()

        import parrot.security.groundedness.guardrail as guardrail_module

        def _boom(*args, **kwargs):
            raise RuntimeError("evidence build blew up")

        monkeypatch.setattr(
            guardrail_module.EvidenceIndex, "from_tool_calls", staticmethod(_boom)
        )
        ai_message = _ai_message(tool_calls=[_tool_call("evidence text")])

        result = await guardrail.check("Some answer.", _ctx(ai_message))

        assert result.action == GuardrailAction.PASS
        assert result.report is None


class TestTelemetryHygiene:
    @pytest.mark.asyncio
    async def test_telemetry_never_carries_atom_raw_values(self, caplog):
        guardrail = GroundednessGuardrail()
        ai_message = _ai_message(
            tool_calls=[_tool_call("Reference invoice INV-2210 for finance@acme.example.com.")],
        )
        # Unsupported atoms whose raw text must never leak into telemetry.
        content = "Please reference invoice INV-9999 and contact bob@other.com."

        with caplog.at_level(logging.INFO):
            result = await guardrail.check(content, _ctx(ai_message))

        assert result.action == GuardrailAction.FLAG
        assert "INV-9999" not in caplog.text
        assert "bob@other.com" not in caplog.text
        assert "INV-2210" not in caplog.text

    @pytest.mark.asyncio
    async def test_telemetry_carries_score_and_counts(self, caplog):
        guardrail = GroundednessGuardrail()
        ai_message = _ai_message(
            tool_calls=[_tool_call("Revenue was $1,243,500 this quarter.")],
        )

        with caplog.at_level(logging.INFO):
            await guardrail.check("Revenue reached $1,243,500.", _ctx(ai_message))

        assert any("score=" in record.getMessage() for record in caplog.records)
        assert any("total_atoms=" in record.getMessage() for record in caplog.records)

    @pytest.mark.asyncio
    async def test_info_log_below_min_alert_score(self, caplog):
        policy = GroundednessPolicy(min_alert_score=0.9)
        guardrail = GroundednessGuardrail(policy=policy)
        ai_message = _ai_message(
            tool_calls=[_tool_call("Reference invoice INV-2210.")],
        )

        with caplog.at_level(logging.INFO):
            await guardrail.check("Reference invoice INV-9999.", _ctx(ai_message))

        assert any("below min_alert_score" in record.getMessage() for record in caplog.records)


class TestStageAndPriority:
    def test_registered_for_output_stage_only(self):
        guardrail = GroundednessGuardrail()
        assert guardrail.stages == {GuardrailStage.OUTPUT}

    def test_observer_priority_band(self):
        """200+ is the documented observer band (Guardrail ABC docstring)."""
        guardrail = GroundednessGuardrail()
        assert guardrail.priority >= 200

    def test_name_is_groundedness(self):
        assert GroundednessGuardrail().name == "groundedness"
