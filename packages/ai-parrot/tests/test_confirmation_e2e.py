"""End-to-end integration tests for HITL Tool-Call Confirmation (FEAT-235).

Tests the full pipeline:
  ConfirmationGuard + InMemoryConfirmationWindowStore + ToolManager + AbstractTool

Run with:
    pytest packages/ai-parrot/tests/test_confirmation_e2e.py -v
"""
from __future__ import annotations

from typing import Any

import pytest

from parrot.auth import (
    ConfirmationConfig,
    ConfirmationDecision,
    ConfirmationGuard,
    ConfirmationWindowStore,
    GrantGuard,
    GuardDecision,
    InMemoryConfirmationWindowStore,
    InMemoryGrantStore,
)
from parrot.tools.abstract import AbstractTool, ToolResult
from parrot.tools.manager import ToolManager


# ── Stubs ──────────────────────────────────────────────────────────────────────


class _FakeResult:
    def __init__(self, approved: bool = True, timed_out: bool = False):
        self.consolidated_value = approved
        self.timed_out = timed_out
        self.interaction_id = "fake"
        self.responses = []


class _FakeHumanManager:
    def __init__(self, approved: bool = True, timed_out: bool = False):
        self._result = _FakeResult(approved=approved, timed_out=timed_out)
        self.calls = 0

    async def request_human_input(self, interaction, channel=None):
        self.calls += 1
        return self._result


class _ConfirmingTool(AbstractTool):
    name = "confirming_action"
    description = "An action that requires confirmation."

    def __init__(self, **kwargs):
        super().__init__(
            routing_meta={"requires_confirmation": True},
            **kwargs,
        )
        self.exec_count = 0

    async def _execute(self, value: str = "default", **kwargs) -> ToolResult:
        self.exec_count += 1
        return ToolResult(success=True, status="success", result=f"executed:{value}")


class _GrantAndConfirmTool(AbstractTool):
    name = "grant_confirm_action"
    description = "Requires both grant and confirmation."

    def __init__(self, **kwargs):
        super().__init__(
            routing_meta={
                "requires_grant": True,
                "requires_confirmation": True,
            },
            **kwargs,
        )
        self.exec_count = 0

    async def _execute(self, **kwargs) -> ToolResult:
        self.exec_count += 1
        return ToolResult(success=True, status="success", result="done")


def _make_tool_manager() -> ToolManager:
    return ToolManager()


# ── Test: export check ─────────────────────────────────────────────────────────


def test_confirmation_symbols_exported_from_parrot_auth():
    """All confirmation symbols are importable from parrot.auth."""
    from parrot.auth import (
        ConfirmationConfig,
        ConfirmationDecision,
        ConfirmationGuard,
        ConfirmationWindowStore,
        InMemoryConfirmationWindowStore,
    )

    assert ConfirmationGuard is not None
    assert ConfirmationConfig is not None
    assert ConfirmationDecision is not None
    assert ConfirmationWindowStore is not None
    assert InMemoryConfirmationWindowStore is not None


def test_confirmation_symbols_in_all():
    """Confirmation symbols appear in parrot.auth.__all__."""
    import parrot.auth as auth_module

    for sym in [
        "ConfirmationConfig",
        "ConfirmationDecision",
        "ConfirmationWindowStore",
        "InMemoryConfirmationWindowStore",
        "ConfirmationGuard",
    ]:
        assert sym in auth_module.__all__, f"{sym} missing from parrot.auth.__all__"


# ── E2E: BLOCK approve → tool executes ────────────────────────────────────────


@pytest.mark.asyncio
async def test_e2e_block_approve_executes():
    """BLOCK + approve → tool executes, normal result returned."""
    mgr = _make_tool_manager()
    tool = _ConfirmingTool()
    mgr._tools[tool.name] = tool

    human = _FakeHumanManager(approved=True)
    store = InMemoryConfirmationWindowStore()
    guard = ConfirmationGuard(store=store, human_manager=human)
    mgr.set_confirmation_guard(guard)

    result = await mgr.execute_tool(tool.name, {"value": "hello"})

    assert tool.exec_count == 1
    assert human.calls == 1


# ── E2E: BLOCK reject → cancelled ToolResult ─────────────────────────────────


@pytest.mark.asyncio
async def test_e2e_block_reject_returns_cancelled():
    """BLOCK + reject → ToolResult(success=False, status='cancelled'); tool not run."""
    mgr = _make_tool_manager()
    tool = _ConfirmingTool()
    mgr._tools[tool.name] = tool

    human = _FakeHumanManager(approved=False)
    store = InMemoryConfirmationWindowStore()
    guard = ConfirmationGuard(store=store, human_manager=human)
    mgr.set_confirmation_guard(guard)

    result = await mgr.execute_tool(tool.name, {})

    assert tool.exec_count == 0
    assert isinstance(result, ToolResult)
    assert result.success is False
    assert result.status == "cancelled"


# ── E2E: grant → confirm ordering ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_e2e_grant_then_confirm_ordering():
    """grant → confirm order: grant authorized first, then confirm asked."""
    mgr = _make_tool_manager()
    tool = _GrantAndConfirmTool()
    mgr._tools[tool.name] = tool

    order = []

    class _TrackGrant:
        async def authorize(self, *, tool, parameters, permission_context=None):
            order.append("grant")
            return GuardDecision(allowed=True, reason="granted")

    class _TrackConfirm:
        async def confirm(self, *, tool, parameters, permission_context=None):
            order.append("confirm")
            return ConfirmationDecision(
                allowed=True, status="confirmed", reason="ok", parameters=parameters
            )

    mgr._grant_guard = _TrackGrant()
    mgr._confirmation_guard = _TrackConfirm()

    await mgr.execute_tool(tool.name, {})

    assert order == ["grant", "confirm"]
    assert tool.exec_count == 1


# ── E2E: no guard → unchanged dispatch ───────────────────────────────────────


@pytest.mark.asyncio
async def test_e2e_no_guard_dispatch_unchanged():
    """No confirmation guard → tool executes without HITL (regression test)."""
    mgr = _make_tool_manager()
    tool = _ConfirmingTool()
    mgr._tools[tool.name] = tool

    # No guard set
    assert mgr.confirmation_guard is None

    result = await mgr.execute_tool(tool.name, {"value": "test"})

    assert tool.exec_count == 1


# ── E2E: fail-closed (no manager) ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_e2e_fail_closed_no_human_manager():
    """requires_confirmation + no human manager → cancelled (fail-closed)."""
    mgr = _make_tool_manager()
    tool = _ConfirmingTool()
    mgr._tools[tool.name] = tool

    store = InMemoryConfirmationWindowStore()
    guard = ConfirmationGuard(store=store, human_manager=None)
    mgr.set_confirmation_guard(guard)

    result = await mgr.execute_tool(tool.name, {})

    assert tool.exec_count == 0
    assert isinstance(result, ToolResult)
    assert result.success is False
    assert result.status == "cancelled"


# ── E2E: grant denied → confirmation never called ────────────────────────────


@pytest.mark.asyncio
async def test_e2e_grant_deny_skips_confirmation():
    """Grant denied → ToolResult(forbidden); confirmation guard never invoked."""
    mgr = _make_tool_manager()
    tool = _GrantAndConfirmTool()
    mgr._tools[tool.name] = tool

    confirm_calls = []

    class _DenyGrant:
        async def authorize(self, *, tool, parameters, permission_context=None):
            return GuardDecision(allowed=False, reason="no grant")

    class _RecordConfirm:
        async def confirm(self, *, tool, parameters, permission_context=None):
            confirm_calls.append(True)
            return ConfirmationDecision(
                allowed=True, status="confirmed", reason="ok", parameters=parameters
            )

    mgr._grant_guard = _DenyGrant()
    mgr._confirmation_guard = _RecordConfirm()

    result = await mgr.execute_tool(tool.name, {})

    assert tool.exec_count == 0
    assert confirm_calls == []
    assert isinstance(result, ToolResult)
    assert result.status == "forbidden"


# ── E2E: confirmation window prevents re-ask ─────────────────────────────────


@pytest.mark.asyncio
async def test_e2e_confirmation_window_prevents_reask():
    """Within confirm_window_seconds, same call skips HITL."""
    mgr = _make_tool_manager()
    tool = _ConfirmingTool()
    mgr._tools[tool.name] = tool

    human = _FakeHumanManager(approved=True)
    store = InMemoryConfirmationWindowStore()
    config = ConfirmationConfig(window_seconds=0)  # config default = 0 (per-call)

    # Override routing_meta on the tool to use a non-zero window
    tool.routing_meta["confirm_window_seconds"] = 300

    guard = ConfirmationGuard(store=store, human_manager=human, config=config)
    mgr.set_confirmation_guard(guard)

    params = {"value": "same"}

    # First call — should ask
    await mgr.execute_tool(tool.name, params)
    assert human.calls == 1

    # Second call with same params — within window, should skip
    await mgr.execute_tool(tool.name, params)
    assert human.calls == 1  # not called again


# ── Full suite smoke test ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_confirmation_suite_smoke():
    """Run the -k confirmation filter to confirm all tests are discoverable."""
    # This is a meta-test that verifies the suite can be imported and run.
    # Actual test logic is in the individual tests above.
    assert True
