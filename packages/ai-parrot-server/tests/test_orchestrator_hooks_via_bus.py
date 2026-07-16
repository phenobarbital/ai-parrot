"""AUTONOMOUS_HOOKS_VIA_BUS wiring tests (FEAT-310 review fix).

Guards against the double-execution regression: the orchestrator must use
exactly ONE hook-consumption path — direct callback (default) XOR bus
subscription (flag on) — never both.
"""
import asyncio
import time

import pytest

from parrot.autonomous.orchestrator import AutonomousOrchestrator
from parrot.core.hooks.models import HookEvent, HookType


async def wait_until(condition, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        await asyncio.sleep(0.01)
    pytest.fail("condition not met within timeout")


def make_orchestrator(hooks_via_bus: bool) -> AutonomousOrchestrator:
    orch = AutonomousOrchestrator(
        use_event_bus=True,
        use_webhooks=False,
    )
    orch._hooks_via_bus = hooks_via_bus  # force, independent of env config
    return orch


async def test_default_uses_direct_callback_only():
    orch = make_orchestrator(hooks_via_bus=False)
    await orch.start()
    try:
        assert orch.hook_manager._callback is not None
        # No bus wiring on the hook manager in default mode.
        assert orch.hook_manager._event_bus is None
    finally:
        await orch.stop()


async def test_flag_on_uses_bus_subscription_only():
    orch = make_orchestrator(hooks_via_bus=True)
    await orch.start()
    try:
        # Mutual exclusion: bus path wired, direct callback NOT set.
        assert orch.hook_manager._callback is None
        assert orch.hook_manager._event_bus is orch.event_bus
    finally:
        await orch.stop()


async def test_flag_on_hook_event_executes_exactly_once():
    orch = make_orchestrator(hooks_via_bus=True)
    await orch.start()
    executions: list[HookEvent] = []

    async def record(event: HookEvent) -> None:
        executions.append(event)

    # _handle_bus_hook_event reads self._handle_hook_event at call time,
    # so patching the attribute redirects the already-wired subscription.
    orch._handle_hook_event = record  # type: ignore[method-assign]

    try:
        dispatch = orch.hook_manager._build_dispatch()
        assert dispatch is not None
        event = HookEvent(
            hook_id="h-test",
            hook_type=HookType.SCHEDULER,
            event_type="tick",
            payload={"n": 1},
            target_type="agent",
            target_id="dummy",
        )
        await dispatch(event)
        await wait_until(lambda: len(executions) >= 1)
        await asyncio.sleep(0.1)  # give a (buggy) second path time to fire
        assert len(executions) == 1  # exactly once — no double execution
        assert executions[0].event_type == "tick"
        assert executions[0].hook_id == "h-test"
    finally:
        await orch.stop()
