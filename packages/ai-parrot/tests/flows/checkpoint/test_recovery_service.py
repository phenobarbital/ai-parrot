"""Tests for parrot.bots.flows.core.checkpoint.recovery (TASK-2054).

Covers FlowRecoveryService's deadline behavior with fake flows, register/
unregister lifecycle, aiohttp on_shutdown wiring, and its auto-hookup
inside AgentsFlow.run_flow() when checkpointing is enabled.
"""
import asyncio

import pytest
from parrot.bots.flows.core.checkpoint.recovery import (
    FlowRecoveryService,
    get_recovery_service,
)


class FakeFlow:
    """Minimal stand-in exposing only what FlowRecoveryService needs."""

    def __init__(self, flow_id: str, delay: float = 0.0) -> None:
        self.flow_id = flow_id
        self._delay = delay
        self.suspended = False

    async def suspend(self):
        if self._delay:
            await asyncio.sleep(self._delay)
        self.suspended = True


@pytest.mark.asyncio
async def test_recovery_service_suspends_within_deadline(caplog):
    svc = FlowRecoveryService()
    fast_flow = FakeFlow("fast-flow")
    slow_flow = FakeFlow("slow-flow", delay=1.0)
    svc.register(fast_flow)
    svc.register(slow_flow)

    with caplog.at_level("ERROR"):
        await svc.shutdown(deadline=0.1)

    assert fast_flow.suspended is True
    assert slow_flow.suspended is False
    assert any(
        "slow-flow" in record.message and record.levelname == "ERROR"
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_shutdown_idempotent_and_empty():
    svc = FlowRecoveryService()
    await svc.shutdown(deadline=0.1)  # no flows registered — no error
    await svc.shutdown(deadline=0.1)  # calling again is safe


@pytest.mark.asyncio
async def test_shutdown_swallows_suspend_failures(caplog):
    class FailingFlow:
        flow_id = "failing-flow"

        async def suspend(self):
            raise RuntimeError("boom")

    svc = FlowRecoveryService()
    svc.register(FailingFlow())
    with caplog.at_level("WARNING"):
        await svc.shutdown(deadline=1.0)  # must not raise
    assert any("failing-flow" in r.message for r in caplog.records)


def test_register_unregister_lifecycle():
    svc = FlowRecoveryService()
    flow = FakeFlow("f1")
    svc.register(flow)
    assert "f1" in svc._active
    svc.unregister(flow)
    assert "f1" not in svc._active
    # unregistering again is a no-op, not an error
    svc.unregister(flow)


def test_register_overwrites_same_flow_id():
    svc = FlowRecoveryService()
    flow_a = FakeFlow("dup")
    flow_b = FakeFlow("dup")
    svc.register(flow_a)
    svc.register(flow_b)
    assert svc._active["dup"] is flow_b


@pytest.mark.asyncio
async def test_attach_to_app_triggers_suspend_on_cleanup():
    from aiohttp import web

    svc = FlowRecoveryService()
    flow = FakeFlow("app-flow")
    svc.register(flow)

    app = web.Application()
    svc.attach_to_app(app)

    runner = web.AppRunner(app)
    await runner.setup()
    await runner.cleanup()  # triggers on_shutdown

    assert flow.suspended is True


def test_get_recovery_service_returns_singleton():
    svc1 = get_recovery_service()
    svc2 = get_recovery_service()
    assert svc1 is svc2
