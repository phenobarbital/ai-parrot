"""Per-run ``require_plan_approval`` override in DevelopmentNode (FEAT-412).

The dev console (``dev.html``) exposes a per-run plan-approval toggle, so the
gate decision can no longer be fixed at flow-construction time. These tests
pin the resolution order implemented in
``DevelopmentNode._check_plan_approval``:

    explicit shared["require_plan_approval"] (True OR False)
        > constructor flag  (when the key is absent, or present as None)

Truthiness is deliberately NOT used: an explicit ``False`` must suppress a
gate the constructor flag would have opened.

Style mirrors ``test_gate_integration.py``'s plan-gate section (same
fixtures, same "resolve the gate from a concurrent task" pattern).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from parrot.flows.dev_loop import DevelopmentOutput, ResearchOutput
from parrot.flows.dev_loop.nodes.development import DevelopmentNode
from parrot.flows.dev_loop.session_state import SessionHost

RUN_ID = "run-plangate01"


@pytest.fixture
def dev_ctx() -> dict:
    return {
        "run_id": RUN_ID,
        "research_output": ResearchOutput(
            jira_issue_key="OPS-1",
            spec_path="sdd/specs/x.spec.md",
            feat_id="FEAT-412",
            branch_name="feat-412-sdd-dev-flow",
            worktree_path="/tmp/feat-412-plan-gate-override",
            log_excerpts=[],
        ),
    }


@pytest.fixture
def dev_dispatcher() -> MagicMock:
    d = MagicMock()
    d.dispatch = AsyncMock(
        return_value=DevelopmentOutput(
            files_changed=["a.py"], commit_shas=["s1"], summary="ok"
        )
    )
    return d


async def _approve_first_gate(host: SessionHost) -> None:
    """Approve whatever gate the node opens, shortly after it opens."""
    await asyncio.sleep(0.01)
    gate_id = next(iter(host.state.gates))
    host.resolve_gate(gate_id, "approved", resolved_by="alice")


# ---------------------------------------------------------------------------
# shared state overrides the constructor flag — both directions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shared_true_overrides_ctor_false(dev_ctx, dev_dispatcher):
    """The UI toggle turns the gate ON for a run built without the flag."""
    node = DevelopmentNode(dispatcher=dev_dispatcher)  # ctor: False
    host = SessionHost(RUN_ID)
    dev_ctx["session_host"] = host
    dev_ctx["require_plan_approval"] = True

    resolver = asyncio.ensure_future(_approve_first_gate(host))
    result = await node.execute(dev_ctx)
    await resolver

    assert isinstance(result, DevelopmentOutput)
    # A real plan_approval gate was opened and awaited.
    assert len(host.state.gates) == 1
    gate = host.state.gates[next(iter(host.state.gates))]
    assert gate.kind == "plan_approval"
    assert gate.status == "approved"
    assert gate.on_expiry == "approve"  # fail-open policy unchanged
    dev_dispatcher.dispatch.assert_awaited()


@pytest.mark.asyncio
async def test_shared_false_overrides_ctor_true(dev_ctx, dev_dispatcher):
    """An explicit False suppresses the gate the ctor flag would have opened."""
    node = DevelopmentNode(dispatcher=dev_dispatcher, require_plan_approval=True)
    host = SessionHost(RUN_ID)
    dev_ctx["session_host"] = host
    dev_ctx["require_plan_approval"] = False

    # No resolver task: if a gate were opened, this would hang.
    result = await asyncio.wait_for(node.execute(dev_ctx), timeout=2)

    assert isinstance(result, DevelopmentOutput)
    assert host.state.gates == {}
    dev_dispatcher.dispatch.assert_awaited()


@pytest.mark.asyncio
async def test_shared_true_with_ctor_true_still_opens_one_gate(
    dev_ctx, dev_dispatcher
):
    """Redundant agreement is not a double gate."""
    node = DevelopmentNode(dispatcher=dev_dispatcher, require_plan_approval=True)
    host = SessionHost(RUN_ID)
    dev_ctx["session_host"] = host
    dev_ctx["require_plan_approval"] = True

    resolver = asyncio.ensure_future(_approve_first_gate(host))
    await node.execute(dev_ctx)
    await resolver

    assert len(host.state.gates) == 1


# ---------------------------------------------------------------------------
# absent / None key → constructor flag (pre-FEAT-412 behavior)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_absent_key_falls_back_to_ctor_false(dev_ctx, dev_dispatcher):
    node = DevelopmentNode(dispatcher=dev_dispatcher)  # ctor: False
    host = SessionHost(RUN_ID)
    dev_ctx["session_host"] = host
    assert "require_plan_approval" not in dev_ctx

    result = await asyncio.wait_for(node.execute(dev_ctx), timeout=2)

    assert isinstance(result, DevelopmentOutput)
    assert host.state.gates == {}


@pytest.mark.asyncio
async def test_absent_key_falls_back_to_ctor_true(dev_ctx, dev_dispatcher):
    node = DevelopmentNode(dispatcher=dev_dispatcher, require_plan_approval=True)
    host = SessionHost(RUN_ID)
    dev_ctx["session_host"] = host

    resolver = asyncio.ensure_future(_approve_first_gate(host))
    result = await node.execute(dev_ctx)
    await resolver

    assert isinstance(result, DevelopmentOutput)
    assert len(host.state.gates) == 1
    assert host.state.gates[next(iter(host.state.gates))].kind == "plan_approval"


@pytest.mark.asyncio
async def test_none_value_is_treated_as_absent(dev_ctx, dev_dispatcher):
    """A form that submits nothing must not silently disable the ctor flag."""
    node = DevelopmentNode(dispatcher=dev_dispatcher, require_plan_approval=True)
    host = SessionHost(RUN_ID)
    dev_ctx["session_host"] = host
    dev_ctx["require_plan_approval"] = None

    resolver = asyncio.ensure_future(_approve_first_gate(host))
    await node.execute(dev_ctx)
    await resolver

    assert len(host.state.gates) == 1


# ---------------------------------------------------------------------------
# the retry-idempotency guard still wins over the override
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_gate_checked_guard_still_wins(dev_ctx, dev_dispatcher):
    """A QA-repair-loop re-entry must not re-open the gate, override or not."""
    node = DevelopmentNode(dispatcher=dev_dispatcher)  # ctor: False
    host = SessionHost(RUN_ID)
    dev_ctx["session_host"] = host
    dev_ctx["require_plan_approval"] = True

    resolver = asyncio.ensure_future(_approve_first_gate(host))
    await node.execute(dev_ctx)
    await resolver
    assert len(host.state.gates) == 1
    assert dev_ctx["_plan_gate_checked"] is True

    # Second entry (repair loop): no new gate, no hang.
    result = await asyncio.wait_for(node.execute(dev_ctx), timeout=2)

    assert isinstance(result, DevelopmentOutput)
    assert len(host.state.gates) == 1  # still exactly one


@pytest.mark.asyncio
async def test_preset_checked_guard_suppresses_override(dev_ctx, dev_dispatcher):
    """``_plan_gate_checked`` already set → the override cannot open a gate."""
    node = DevelopmentNode(dispatcher=dev_dispatcher)
    host = SessionHost(RUN_ID)
    dev_ctx["session_host"] = host
    dev_ctx["require_plan_approval"] = True
    dev_ctx["_plan_gate_checked"] = True

    result = await asyncio.wait_for(node.execute(dev_ctx), timeout=2)

    assert isinstance(result, DevelopmentOutput)
    assert host.state.gates == {}


# ---------------------------------------------------------------------------
# no-host legacy fallback still applies to the override path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_override_without_host_warns_and_proceeds(
    dev_ctx, dev_dispatcher, caplog
):
    import logging

    node = DevelopmentNode(dispatcher=dev_dispatcher)  # ctor: False
    dev_ctx["require_plan_approval"] = True  # no session_host in ctx

    with caplog.at_level(logging.WARNING):
        result = await asyncio.wait_for(node.execute(dev_ctx), timeout=2)

    assert isinstance(result, DevelopmentOutput)
    assert any("no session_host" in rec.message for rec in caplog.records)
    dev_dispatcher.dispatch.assert_awaited()
