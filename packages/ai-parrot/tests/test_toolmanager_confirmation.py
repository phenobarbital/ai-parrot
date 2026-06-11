"""Integration tests for ToolManager confirmation guard dispatch gate (TASK-1536).

Tests: set_confirmation_guard(), confirmation_guard property, dispatch with
approve/cancel, no-guard regression, grant→confirm ordering.

Run with:
    pytest packages/ai-parrot/tests/test_toolmanager_confirmation.py -v
"""
from __future__ import annotations

from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.auth.confirmation import (
    ConfirmationConfig,
    ConfirmationDecision,
    ConfirmationGuard,
    InMemoryConfirmationWindowStore,
)
from parrot.auth.grants import GrantGuard, GuardDecision, InMemoryGrantStore
from parrot.tools.abstract import AbstractTool, ToolResult
from parrot.tools.manager import ToolManager


# ── Stubs ──────────────────────────────────────────────────────────────────────


class _FakeResult:
    """Minimal stub for InteractionResult."""

    def __init__(self, approved: bool = True, timed_out: bool = False):
        self.consolidated_value = approved
        self.timed_out = timed_out
        self.interaction_id = "fake-id"
        self.responses = []


class _FakeManager:
    """Stub HumanInteractionManager."""

    def __init__(self, approved: bool = True, timed_out: bool = False):
        self._result = _FakeResult(approved=approved, timed_out=timed_out)
        self.calls = 0

    async def request_human_input(self, interaction, channel=None):
        self.calls += 1
        return self._result


class _SimpleConfirmingTool(AbstractTool):
    """Minimal AbstractTool that requires confirmation."""

    name = "confirming_tool"
    description = "A tool that requires confirmation."

    def __init__(self, requires_confirmation: bool = True, **kwargs):
        super().__init__(
            routing_meta={"requires_confirmation": requires_confirmation},
            **kwargs,
        )
        self._exec_count = 0

    async def _execute(self, **kwargs) -> ToolResult:
        self._exec_count += 1
        return ToolResult(success=True, status="success", result="executed")


class _GrantAndConfirmTool(AbstractTool):
    """Tool that requires both a grant AND confirmation."""

    name = "grant_confirm_tool"
    description = "Needs both grant and confirmation."

    def __init__(self, **kwargs):
        super().__init__(
            routing_meta={
                "requires_grant": True,
                "requires_confirmation": True,
            },
            **kwargs,
        )
        self._exec_count = 0

    async def _execute(self, **kwargs) -> ToolResult:
        self._exec_count += 1
        return ToolResult(success=True, status="success", result="executed")


def _make_manager() -> ToolManager:
    """Create a fresh ToolManager for each test."""
    return ToolManager()


# ── Test: setter and property ──────────────────────────────────────────────────


def test_set_confirmation_guard_and_property():
    """set_confirmation_guard() stores guard; confirmation_guard property returns it."""
    mgr = _make_manager()
    store = InMemoryConfirmationWindowStore()
    guard = ConfirmationGuard(store=store)

    assert mgr.confirmation_guard is None
    mgr.set_confirmation_guard(guard)
    assert mgr.confirmation_guard is guard


# ── Test: no-guard regression ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_guard_dispatch_unchanged():
    """Without a confirmation guard, dispatch is identical to today."""
    mgr = _make_manager()
    tool = _SimpleConfirmingTool(requires_confirmation=True)
    mgr.register_tool(
        name=tool.name,
        description=tool.description,
        input_schema={},
        function=tool.execute,
    )
    # Register as AbstractTool in the tool registry
    mgr._tools[tool.name] = tool

    result = await mgr.execute_tool(tool.name, {})
    # Should execute without asking for confirmation
    assert tool._exec_count == 1


# ── Test: approve → execution ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_confirmation_approve_executes_tool():
    """Approval → tool executes; result returned."""
    mgr = _make_manager()
    tool = _SimpleConfirmingTool(requires_confirmation=True)
    mgr._tools[tool.name] = tool

    fake_human = _FakeManager(approved=True)
    store = InMemoryConfirmationWindowStore()
    guard = ConfirmationGuard(store=store, human_manager=fake_human)
    mgr.set_confirmation_guard(guard)

    result = await mgr.execute_tool(tool.name, {})

    # Tool executed
    assert tool._exec_count == 1
    assert fake_human.calls == 1


# ── Test: reject → cancelled ToolResult ───────────────────────────────────────


@pytest.mark.asyncio
async def test_confirmation_reject_returns_cancelled_toolresult():
    """Rejection → ToolResult(success=False, status='cancelled'); tool NOT executed."""
    mgr = _make_manager()
    tool = _SimpleConfirmingTool(requires_confirmation=True)
    mgr._tools[tool.name] = tool

    fake_human = _FakeManager(approved=False)
    store = InMemoryConfirmationWindowStore()
    guard = ConfirmationGuard(store=store, human_manager=fake_human)
    mgr.set_confirmation_guard(guard)

    result = await mgr.execute_tool(tool.name, {})

    assert tool._exec_count == 0
    assert fake_human.calls == 1
    assert isinstance(result, ToolResult)
    assert result.success is False
    assert result.status == "cancelled"


# ── Test: timeout → timeout ToolResult ────────────────────────────────────────


@pytest.mark.asyncio
async def test_confirmation_timeout_returns_timeout_toolresult():
    """Timeout → ToolResult(success=False, status='timeout'); tool NOT executed."""
    mgr = _make_manager()
    tool = _SimpleConfirmingTool(requires_confirmation=True)
    mgr._tools[tool.name] = tool

    fake_human = _FakeManager(timed_out=True)
    store = InMemoryConfirmationWindowStore()
    guard = ConfirmationGuard(store=store, human_manager=fake_human)
    mgr.set_confirmation_guard(guard)

    result = await mgr.execute_tool(tool.name, {})

    assert tool._exec_count == 0
    assert isinstance(result, ToolResult)
    assert result.success is False
    assert result.status == "timeout"


# ── Test: non-confirmation tool passes through guard ──────────────────────────


@pytest.mark.asyncio
async def test_non_confirmation_tool_skips_guard():
    """Tool without requires_confirmation passes guard without HITL call."""
    mgr = _make_manager()
    tool = _SimpleConfirmingTool(requires_confirmation=False)
    mgr._tools[tool.name] = tool

    fake_human = _FakeManager(approved=True)
    store = InMemoryConfirmationWindowStore()
    guard = ConfirmationGuard(store=store, human_manager=fake_human)
    mgr.set_confirmation_guard(guard)

    result = await mgr.execute_tool(tool.name, {})

    assert tool._exec_count == 1
    assert fake_human.calls == 0  # no HITL call


# ── Test: grant → confirm order when both guards set ──────────────────────────


@pytest.mark.asyncio
async def test_grant_then_confirm_order():
    """Tool requiring both grant and confirmation: grant authorized first, then confirmed."""
    mgr = _make_manager()
    tool = _GrantAndConfirmTool()
    mgr._tools[tool.name] = tool

    call_order = []

    class _OrderTrackingGrantGuard:
        async def authorize(self, *, tool, parameters, permission_context=None):
            call_order.append("grant")
            return GuardDecision(allowed=True, reason="grant ok")

    class _OrderTrackingConfirmGuard:
        async def confirm(self, *, tool, parameters, permission_context=None):
            call_order.append("confirm")
            return ConfirmationDecision(
                allowed=True, status="confirmed", reason="ok", parameters=parameters
            )

    mgr._grant_guard = _OrderTrackingGrantGuard()
    mgr._confirmation_guard = _OrderTrackingConfirmGuard()

    result = await mgr.execute_tool(tool.name, {})

    assert call_order == ["grant", "confirm"]
    assert tool._exec_count == 1


# ── Test: grant denies → confirmation never called ────────────────────────────


@pytest.mark.asyncio
async def test_grant_deny_skips_confirmation():
    """If grant denies, confirmation guard is never invoked."""
    mgr = _make_manager()
    tool = _GrantAndConfirmTool()
    mgr._tools[tool.name] = tool

    confirm_called = []

    class _DenyGrantGuard:
        async def authorize(self, *, tool, parameters, permission_context=None):
            return GuardDecision(allowed=False, reason="no grant")

    class _RecordConfirmGuard:
        async def confirm(self, *, tool, parameters, permission_context=None):
            confirm_called.append(True)
            return ConfirmationDecision(
                allowed=True, status="confirmed", reason="ok", parameters=parameters
            )

    mgr._grant_guard = _DenyGrantGuard()
    mgr._confirmation_guard = _RecordConfirmGuard()

    result = await mgr.execute_tool(tool.name, {})

    assert tool._exec_count == 0
    assert confirm_called == []  # never called
    assert isinstance(result, ToolResult)
    assert result.status == "forbidden"
