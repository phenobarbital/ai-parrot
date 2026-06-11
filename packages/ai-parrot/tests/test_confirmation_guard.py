"""Unit tests for ConfirmationGuard core lifecycle.

Tests BLOCK/SUSPEND paths, fail-closed, window hits, and non-confirmation
passthrough — with a stub HumanInteractionManager.

Run with:
    pytest packages/ai-parrot/tests/test_confirmation_guard.py -v
"""
from __future__ import annotations

from typing import Any, Optional
from unittest.mock import MagicMock

import pytest

from parrot.auth.confirmation import (
    ConfirmationConfig,
    ConfirmationDecision,
    ConfirmationGuard,
    InMemoryConfirmationWindowStore,
    compute_args_hash,
)
from parrot.human.models import InteractionResult, InteractionStatus, InteractionType


# ── Stubs and Fixtures ─────────────────────────────────────────────────────────


class _FakeInteractionResult:
    """Minimal stub for InteractionResult."""

    def __init__(self, approved: Optional[bool] = None, timed_out: bool = False, form_value: Any = None):
        self.consolidated_value = approved if form_value is None else form_value
        self.timed_out = timed_out
        self.status = InteractionStatus.TIMEOUT if timed_out else InteractionStatus.COMPLETED
        self.interaction_id = "fake-interaction-id"
        self.responses = []


class _FakeManager:
    """Stub HumanInteractionManager for testing."""

    def __init__(self, result: _FakeInteractionResult):
        self._result = result
        self.calls = 0
        self.async_calls = 0

    async def request_human_input(self, interaction, channel=None):
        self.calls += 1
        return self._result

    async def request_human_input_async(self, interaction, channel=None, schedule_timeout=True):
        self.async_calls += 1
        return "fake-interaction-id"


def _make_tool(
    name: str = "my_tool",
    requires_confirmation: bool = False,
    wait_strategy: Optional[str] = None,
    allow_edit: bool = False,
    confirm_template: Optional[str] = None,
    confirm_window_seconds: int = 0,
):
    """Create a minimal AbstractTool stub."""
    tool = MagicMock()
    tool.name = name
    tool.routing_meta = {
        "requires_confirmation": requires_confirmation,
    }
    if wait_strategy is not None:
        tool.routing_meta["wait_strategy"] = wait_strategy
    if allow_edit:
        tool.routing_meta["allow_edit"] = True
    if confirm_template is not None:
        tool.routing_meta["confirm_template"] = confirm_template
    if confirm_window_seconds:
        tool.routing_meta["confirm_window_seconds"] = confirm_window_seconds
    # args_schema stub (no fields, passthrough validation)
    tool.args_schema = None
    return tool


# ── Test: not_required passthrough ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_confirm_not_required_passthrough():
    """Tool without requires_confirmation → allowed=True, status=not_required, no HITL call."""
    store = InMemoryConfirmationWindowStore()
    fake_manager = _FakeManager(_FakeInteractionResult(approved=True))
    guard = ConfirmationGuard(store=store, human_manager=fake_manager)
    tool = _make_tool(requires_confirmation=False)

    decision = await guard.confirm(tool=tool, parameters={"x": 1})

    assert decision.allowed is True
    assert decision.status == "not_required"
    assert fake_manager.calls == 0  # no HITL call


# ── Test: BLOCK + approve ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_confirm_block_approved():
    """BLOCK + approval → allowed=True, status=confirmed."""
    store = InMemoryConfirmationWindowStore()
    fake_manager = _FakeManager(_FakeInteractionResult(approved=True))
    guard = ConfirmationGuard(store=store, human_manager=fake_manager)
    tool = _make_tool(requires_confirmation=True)

    decision = await guard.confirm(tool=tool, parameters={"x": 1})

    assert decision.allowed is True
    assert decision.status == "confirmed"
    assert fake_manager.calls == 1


# ── Test: BLOCK + reject ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_confirm_block_rejected():
    """BLOCK + rejection → allowed=False, status=cancelled."""
    store = InMemoryConfirmationWindowStore()
    fake_manager = _FakeManager(_FakeInteractionResult(approved=False))
    guard = ConfirmationGuard(store=store, human_manager=fake_manager)
    tool = _make_tool(requires_confirmation=True)

    decision = await guard.confirm(tool=tool, parameters={"y": 2})

    assert decision.allowed is False
    assert decision.status == "cancelled"
    assert fake_manager.calls == 1


# ── Test: timeout ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_confirm_timeout():
    """No response (timed_out=True) → allowed=False, status=timeout."""
    store = InMemoryConfirmationWindowStore()
    fake_manager = _FakeManager(_FakeInteractionResult(timed_out=True))
    guard = ConfirmationGuard(store=store, human_manager=fake_manager)
    tool = _make_tool(requires_confirmation=True)

    decision = await guard.confirm(tool=tool, parameters={})

    assert decision.allowed is False
    assert decision.status == "timeout"


# ── Test: SUSPEND raises HumanInteractionInterrupt ────────────────────────────


@pytest.mark.asyncio
async def test_confirm_suspend_raises_interrupt():
    """SUSPEND wait strategy → request_human_input_async called, interrupt raised."""
    from parrot.core.exceptions import HumanInteractionInterrupt

    store = InMemoryConfirmationWindowStore()
    fake_manager = _FakeManager(_FakeInteractionResult(approved=True))
    guard = ConfirmationGuard(store=store, human_manager=fake_manager)
    tool = _make_tool(requires_confirmation=True, wait_strategy="suspend")

    with pytest.raises(HumanInteractionInterrupt):
        await guard.confirm(tool=tool, parameters={"z": 3})

    assert fake_manager.async_calls == 1
    assert fake_manager.calls == 0


# ── Test: fail-closed without manager ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_confirm_fail_closed_no_manager():
    """requires_confirmation + no human_manager → denied (cancelled)."""
    store = InMemoryConfirmationWindowStore()
    guard = ConfirmationGuard(store=store, human_manager=None)
    tool = _make_tool(requires_confirmation=True)

    decision = await guard.confirm(tool=tool, parameters={"a": 1})

    assert decision.allowed is False
    assert decision.status == "cancelled"
    assert "fail-closed" in decision.reason.lower() or "no human manager" in decision.reason.lower()


# ── Test: window hit skips prompt ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_confirm_window_skips_prompt():
    """Within confirm_window_seconds for same args_hash → allowed, no HITL call."""
    store = InMemoryConfirmationWindowStore()
    params = {"employee_id": 42}
    args_hash = compute_args_hash(params)

    # Manually record a window
    await store.record("anonymous", "my_tool", args_hash, window_seconds=300)

    fake_manager = _FakeManager(_FakeInteractionResult(approved=True))
    # Use a per-tool window so the guard checks the store
    guard = ConfirmationGuard(
        store=store,
        human_manager=fake_manager,
        config=ConfirmationConfig(window_seconds=0),  # config default is 0
    )
    tool = _make_tool(
        requires_confirmation=True,
        confirm_window_seconds=300,  # routing_meta override
    )

    decision = await guard.confirm(tool=tool, parameters=params)

    assert decision.allowed is True
    assert fake_manager.calls == 0  # no HITL call (window hit)


# ── Test: window hit not triggered on different args ──────────────────────────


@pytest.mark.asyncio
async def test_confirm_window_reasks_on_diff_args():
    """Different args_hash re-asks even within window."""
    store = InMemoryConfirmationWindowStore()

    # Record window for params_a
    params_a = {"employee_id": 42}
    args_hash_a = compute_args_hash(params_a)
    await store.record("anonymous", "my_tool", args_hash_a, window_seconds=300)

    fake_manager = _FakeManager(_FakeInteractionResult(approved=True))
    guard = ConfirmationGuard(
        store=store,
        human_manager=fake_manager,
        config=ConfirmationConfig(window_seconds=0),
    )
    tool = _make_tool(requires_confirmation=True, confirm_window_seconds=300)

    # Use different params — different hash
    params_b = {"employee_id": 99}
    decision = await guard.confirm(tool=tool, parameters=params_b)

    # Should have called HITL (different args)
    assert fake_manager.calls == 1
    assert decision.allowed is True  # approved by fake_manager


# ── Test: window=0 (config default) always re-asks ───────────────────────────


@pytest.mark.asyncio
async def test_confirm_window_zero_always_reasks():
    """window_seconds=0 (default) → always re-asks, store never consulted for hit."""
    store = InMemoryConfirmationWindowStore()
    params = {"x": 1}

    fake_manager = _FakeManager(_FakeInteractionResult(approved=True))
    guard = ConfirmationGuard(
        store=store,
        human_manager=fake_manager,
        config=ConfirmationConfig(window_seconds=0),
    )
    tool = _make_tool(requires_confirmation=True)  # no routing_meta override

    # First call
    decision1 = await guard.confirm(tool=tool, parameters=params)
    assert decision1.allowed is True
    assert fake_manager.calls == 1

    # Second call with same params — should re-ask
    decision2 = await guard.confirm(tool=tool, parameters=params)
    assert decision2.allowed is True
    assert fake_manager.calls == 2
