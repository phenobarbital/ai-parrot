"""Unit tests for the HITL ExpenseApprovalAgent and its approval tools.

These tests exercise the wiring in ``agents/expense_approval.py`` without any
network I/O: the ``HumanInteractionManager`` is mocked and installed as the
process-wide default.

Run: ``pytest packages/ai-parrot/tests/agents/test_expense_approval.py -v``
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.core.exceptions import HumanInteractionInterrupt
from parrot.human import (
    InteractionStatus,
    InteractionType,
    Severity,
    TimeoutAction,
    set_default_human_manager,
)
from parrot.human.models import (
    EscalationActionType,
    InteractionResult,
)


# ---------------------------------------------------------------------------
# Load agents/expense_approval.py directly (the repo's ``agents/`` dir is not a
# package and would otherwise shadow the stdlib ``operator`` module on sys.path).
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[4]
_AGENT_PATH = _REPO_ROOT / "agents" / "expense_approval.py"


def _load_agent_module():
    spec = importlib.util.spec_from_file_location(
        "expense_approval_agent_under_test", _AGENT_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


m = _load_agent_module()


@pytest.fixture
def fake_manager():
    """A MagicMock manager installed as the default, with a teams channel."""
    manager = MagicMock()
    manager.channels = {"teams": MagicMock()}
    manager._policies = {}
    manager._actions = {}
    set_default_human_manager(manager)
    yield manager
    set_default_human_manager(None)


def _wire_tool(tool, *, approver="boss@corp.com", policy_id="pol-1", timeout=60.0):
    tool.approver_email = approver
    tool.policy_id = policy_id
    tool.tier1_timeout = timeout
    return tool


# ---------------------------------------------------------------------------
# Policy construction
# ---------------------------------------------------------------------------


def test_build_policy_contiguous_tiers_and_email_tier2(monkeypatch):
    monkeypatch.setenv("EXPENSE_TIER2_EMAILS", "finance@corp.com, oncall@corp.com")
    agent = m.ExpenseApprovalAgent.__new__(m.ExpenseApprovalAgent)
    policy = agent._build_policy("boss@corp.com", tier1_timeout=120.0, tier2_timeout=3600.0)

    assert [t.level for t in policy.tiers] == [1, 2]
    tier1, tier2 = policy.tiers
    assert tier1.action_type == EscalationActionType.INTERACT
    assert tier1.channel_type == "teams"
    assert tier1.target_humans == ["boss@corp.com"]
    assert tier1.timeout == 120.0
    assert tier2.action_type == EscalationActionType.NOTIFY
    assert tier2.action_metadata["kind"] == "email"
    assert tier2.action_metadata["to"] == ["finance@corp.com", "oncall@corp.com"]
    assert "{question}" in tier2.action_metadata["subject_template"]


# ---------------------------------------------------------------------------
# BLOCK tool — request_quick_approval
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_quick_tool_blocks_and_passes_correct_interaction(fake_manager):
    result = InteractionResult(
        interaction_id="i1",
        status=InteractionStatus.COMPLETED,
        consolidated_value=True,
    )
    fake_manager.request_human_input = AsyncMock(return_value=result)

    tool = _wire_tool(m.QuickTeamsApprovalTool())
    out = await tool._execute(
        amount=40.0, reason="duplicate charge", requestor="alice@corp.com",
        currency="USD", severity="normal",
    )

    fake_manager.request_human_input.assert_awaited_once()
    args, kwargs = fake_manager.request_human_input.call_args
    interaction = args[0]
    assert kwargs["channel"] == "teams"
    assert interaction.interaction_type == InteractionType.APPROVAL
    assert interaction.timeout_action == TimeoutAction.ESCALATE
    assert interaction.policy_id == "pol-1"
    assert interaction.target_humans == ["boss@corp.com"]
    assert interaction.severity == Severity.NORMAL
    assert interaction.source_agent == "expense_approval"
    assert "approved" in out.lower()


@pytest.mark.asyncio
async def test_quick_tool_reports_rejection(fake_manager):
    fake_manager.request_human_input = AsyncMock(
        return_value=InteractionResult(
            interaction_id="i2", status=InteractionStatus.COMPLETED,
            consolidated_value=False,
        )
    )
    tool = _wire_tool(m.QuickTeamsApprovalTool())
    out = await tool._execute(amount=99.0, reason="x", requestor="bob@corp.com")
    assert "denied" in out.lower()


@pytest.mark.asyncio
async def test_quick_tool_reports_escalation(fake_manager):
    fake_manager.request_human_input = AsyncMock(
        return_value=InteractionResult(
            interaction_id="i3", status=InteractionStatus.ESCALATED,
            escalated=True, action_metadata={"message": "Emailed finance@corp.com"},
        )
    )
    tool = _wire_tool(m.QuickTeamsApprovalTool())
    out = await tool._execute(amount=5000.0, reason="x", requestor="bob@corp.com")
    assert "escalated" in out.lower()
    assert "finance@corp.com" in out


@pytest.mark.asyncio
async def test_quick_tool_errors_when_no_teams_channel(fake_manager):
    fake_manager.channels = {}  # teams not connected
    tool = _wire_tool(m.QuickTeamsApprovalTool())
    out = await tool._execute(amount=10.0, reason="x", requestor="z@corp.com")
    assert "unavailable" in out.lower()


@pytest.mark.asyncio
async def test_quick_tool_errors_when_not_configured(fake_manager):
    tool = m.QuickTeamsApprovalTool()  # no approver / policy wired
    out = await tool._execute(amount=10.0, reason="x", requestor="z@corp.com")
    assert "not" in out.lower() and "config" in out.lower()


# ---------------------------------------------------------------------------
# SUSPEND tool — request_approval_with_escalation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_escalating_tool_suspends_with_interrupt(fake_manager):
    fake_manager.request_human_input_async = AsyncMock(return_value="iid-42")
    tool = _wire_tool(m.EscalatingTeamsApprovalTool())

    with pytest.raises(HumanInteractionInterrupt) as exc:
        await tool._execute(
            amount=5000.0, reason="new laptop", requestor="carol@corp.com",
            severity="high",
        )

    assert exc.value.interaction_id == "iid-42"
    assert exc.value.policy_id == "pol-1"
    fake_manager.request_human_input_async.assert_awaited_once()
    _, kwargs = fake_manager.request_human_input_async.call_args
    assert kwargs["channel"] == "teams"
    assert kwargs["schedule_timeout"] is True


@pytest.mark.asyncio
async def test_escalating_tool_errors_when_manager_missing():
    set_default_human_manager(None)
    tool = _wire_tool(m.EscalatingTeamsApprovalTool())
    out = await tool._execute(amount=1.0, reason="x", requestor="z@corp.com")
    assert "unavailable" in out.lower()


@pytest.mark.asyncio
async def test_escalating_tool_errors_when_no_teams_channel(fake_manager):
    fake_manager.channels = {}  # teams not connected
    tool = _wire_tool(m.EscalatingTeamsApprovalTool())
    out = await tool._execute(amount=10.0, reason="x", requestor="z@corp.com")
    assert "unavailable" in out.lower()


# ---------------------------------------------------------------------------
# Tool metadata
# ---------------------------------------------------------------------------


def test_tool_names_and_schema():
    assert m.QuickTeamsApprovalTool().name == "request_quick_approval"
    assert m.EscalatingTeamsApprovalTool().name == "request_approval_with_escalation"
    props = m.QuickTeamsApprovalTool().args_schema.model_json_schema()["properties"]
    assert {"amount", "reason", "requestor"}.issubset(props)
