"""Unit tests for HumanTool severity input field.

TASK-1282 — FEAT-194 hitl-escalation-tier
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from parrot.human.models import (
    InteractionResult,
    InteractionStatus,
    Severity,
)
from parrot.human.tool import HumanTool, HumanToolInput


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_manager(severity_capture=None):
    """Mock manager that captures the built interaction."""
    mgr = AsyncMock()

    async def fake_request(interaction, channel="telegram"):
        if severity_capture is not None:
            severity_capture.append(interaction.severity)
        return InteractionResult(
            interaction_id=interaction.interaction_id,
            status=InteractionStatus.COMPLETED,
            consolidated_value="done",
        )

    mgr.request_human_input = fake_request
    return mgr


def _make_tool(severity_capture=None):
    mgr = _make_manager(severity_capture)
    tool = HumanTool(
        manager=mgr,
        default_targets=["tg:123"],
    )
    return tool


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestSeverityPropagates:

    @pytest.mark.asyncio
    async def test_severity_critical_propagates(self):
        """ask_human(severity='critical') propagates Severity.CRITICAL to interaction."""
        captured = []
        tool = _make_tool(captured)

        await tool._execute(
            question="Drop production DB?",
            severity="critical",
        )

        assert len(captured) == 1
        assert captured[0] == Severity.CRITICAL

    @pytest.mark.asyncio
    async def test_severity_high_propagates(self):
        """ask_human(severity='high') propagates Severity.HIGH."""
        captured = []
        tool = _make_tool(captured)

        await tool._execute(
            question="Migrate customer data?",
            severity="high",
        )

        assert captured[0] == Severity.HIGH

    @pytest.mark.asyncio
    async def test_default_severity_is_normal(self):
        """When severity is not provided, default is Severity.NORMAL."""
        captured = []
        tool = _make_tool(captured)

        await tool._execute(question="Which option?")

        assert captured[0] == Severity.NORMAL

    @pytest.mark.asyncio
    async def test_severity_low_propagates(self):
        """ask_human(severity='low') propagates Severity.LOW."""
        captured = []
        tool = _make_tool(captured)

        await tool._execute(question="Optional review?", severity="low")

        assert captured[0] == Severity.LOW


class TestInvalidSeverity:

    @pytest.mark.asyncio
    async def test_invalid_severity_returns_actionable_error(self):
        """Invalid severity returns an error string starting with 'HumanTool error:'."""
        tool = _make_tool()

        result = await tool._execute(
            question="Approve?",
            severity="urgent",  # not a valid value
        )

        assert isinstance(result, str)
        assert result.startswith("HumanTool error: unknown severity")
        assert "urgent" in result
        assert "low, normal, high, critical" in result


class TestToolDescription:

    def test_tool_description_mentions_severity_levels(self):
        """Tool input schema description mentions all four severity levels."""
        schema_str = str(HumanToolInput.model_fields["severity"].description)
        for level in ("low", "normal", "high", "critical"):
            assert level in schema_str.lower(), f"Expected '{level}' in severity description"

    def test_severity_field_exists_in_schema(self):
        """severity field is present in HumanToolInput schema."""
        assert "severity" in HumanToolInput.model_fields
