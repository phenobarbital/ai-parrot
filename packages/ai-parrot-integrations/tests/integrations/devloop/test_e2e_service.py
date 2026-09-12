"""FEAT-555 TASK-3210 — service-level e2e: Redis loss, restart re-attach."""

from __future__ import annotations

import asyncio
import sys
import time

import pytest

from parrot.flows.dev_loop.session_state import ApprovalGate, GateOpened, NodeStarted, RunClosed, SessionHost
from parrot.integrations.devloop import service as svc
from parrot.integrations.devloop.models import DevLoopCommand, Requester, RunRecord
from parrot.integrations.devloop.transport import NullTransport

pytestmark = pytest.mark.integration

_REQ = Requester(transport="slack", tenant_id="T1", user_id="U1")


async def _wait_until(predicate, timeout: float = 5.0, interval: float = 0.02) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while not predicate():
        if asyncio.get_event_loop().time() > deadline:
            raise AssertionError("condition never became true")
        await asyncio.sleep(interval)


@pytest.mark.asyncio
async def test_tail_survives_redis_loss(fake_redis, devloop_config, slack_api):
    """A transient xread failure inside FlowStreamMultiplexer.state_tail() must not lose or duplicate events.

    ``state_tail()`` (streaming.py:436-439) already retries internally
    (fixed 0.5s backoff) on any xread error, so the service's background
    ``_tail`` task must keep folding events into the record afterwards —
    no gap, no duplicate ``gate_opened`` (spec §7 "Redis outage while
    tailing", AC13).
    """
    run_id = "run-redisloss1"
    host = SessionHost(run_id=run_id)
    key = f"flow:{run_id}:actions"

    # Seed one event BEFORE the tail starts — state_replay's xrange picks it up.
    env1 = host.apply(NodeStarted(node_id="ideation"))
    await fake_redis.xadd(key, {"envelope": env1.model_dump_json()})

    service = svc.DevLoopDispatchService(config=devloop_config, transport=NullTransport(), redis=fake_redis)
    record = RunRecord(
        run_id=run_id,
        kind="feature",
        title="t",
        requester=_REQ,
        channel_id="C1",
        command_endpoint="unix:///tmp/x.sock",
        command_token="tok",
        phase="running",
        started_at=time.time(),
    )
    await service.registry.save(record)

    # last_seen=0 (not None): the AHP-reconnect path uses a real xrange cursor
    # (session_state.py:317/347) rather than "$", which the fixture's fake
    # xread — like the core dev_loop tests' own fake (test_streaming.py:56) —
    # never resolves; a numeric cursor is required for the fake to observe
    # entries added *after* the tail has started (env2/env3 below).
    task = asyncio.create_task(service._tail(record, last_seen=0), name=f"devloop-tail-{run_id}")
    try:
        await _wait_until(lambda: service.record(run_id).current_node == "ideation")

        # Inject one transient xread failure for the live-tail phase.
        fake_redis.fail_next_xread = 1

        gate = ApprovalGate(gate_id="oq-1", kind="open_questions", node_id="ideation", title="Q", questions=["q1"])
        env2 = host.apply(GateOpened(gate=gate))
        await fake_redis.xadd(key, {"envelope": env2.model_dump_json()})

        # The gate still arrives exactly once despite the injected blip.
        await _wait_until(lambda: service.pending_gate(run_id) is not None, timeout=5.0)
        assert fake_redis.fail_next_xread == 0  # the injected failure was actually consumed

        env3 = host.apply(RunClosed(outcome="succeeded"))
        await fake_redis.xadd(key, {"envelope": env3.model_dump_json()})
        await _wait_until(lambda: service.record(run_id).phase == "completed", timeout=5.0)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_restart_reattach(fake_redis, devloop_config, slack_api, fake_child):
    """A run started by one service instance is re-attached and driven to completion by a fresh one.

    ``service.stop()`` only cancels tail/supervise tasks (G7 — children
    keep running); a brand-new ``DevLoopDispatchService`` sharing the same
    Redis then re-attaches via ``start()`` and resumes tailing to the
    terminal action (spec §7 "Re-attach on start", AC13).
    """
    devloop_config.command = [sys.executable, fake_child]

    s1 = svc.DevLoopDispatchService(config=devloop_config, transport=NullTransport(), redis=fake_redis)
    pending_id = await s1.dispatch(
        DevLoopCommand(action="dispatch", type="feature", prompt="Build the thing. Now"), _REQ, "C1"
    )
    record = await s1.confirm(pending_id, _REQ)
    await _wait_until(lambda: s1.record(record.run_id).phase == "running", timeout=10.0)

    await s1.stop()  # cancels s1's own tail/supervise tasks — the fake_child process keeps running

    s2 = svc.DevLoopDispatchService(config=devloop_config, transport=NullTransport(), redis=fake_redis)
    await s2.start()
    try:
        assert any(t.get_name() == f"devloop-tail-{record.run_id}" for t in s2._tasks)

        # fake_child does not run a real dev-loop graph — publish the terminal
        # action on the stream ourselves, exactly as DevLoopRunner would.
        host = SessionHost(run_id=record.run_id)
        env = host.apply(RunClosed(outcome="succeeded", pr_url="http://pr/1"))
        await fake_redis.xadd(f"flow:{record.run_id}:actions", {"envelope": env.model_dump_json()})

        await _wait_until(lambda: any(c[0] == "post_terminal" for c in s2.transport.calls), timeout=5.0)
        assert (await s2.registry.get(record.run_id)).phase == "completed"
    finally:
        await s2.stop()
