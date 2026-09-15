"""Tests for RunStateTail (TASK-3203) — stream seeded with a real SessionHost, FakeRedis from conftest."""

from __future__ import annotations

import asyncio

import pytest

from parrot.flows.dev_loop.session_state import (
    ApprovalGate,
    GateOpened,
    GateResolved,
    NodeCompleted,
    NodeStarted,
    RunClosed,
    SessionHost,
)
from parrot.integrations.devloop.tail import RunStateTail, _frame_to_event

RUN = "run-tail0001"


def _key() -> str:
    return f"flow:{RUN}:actions"


async def _seed(redis, host, *actions):
    for a in actions:
        env = host.apply(a)
        await redis.xadd(_key(), {"envelope": env.model_dump_json()})


async def _collect(agen, n, timeout=2.0):
    """Pull exactly ``n`` events off a (possibly never-ending) events() stream, then close it.

    Without a terminal action in the seed, ``events()`` legitimately never
    stops on its own (it keeps live-tailing) — a plain ``[e async for e
    in ...]`` would hang forever, so tests that don't seed a terminal
    action must bound their consumption instead.
    """
    events = []
    ait = agen.__aiter__()
    try:
        for _ in range(n):
            events.append(await asyncio.wait_for(ait.__anext__(), timeout=timeout))
    finally:
        await ait.aclose()
    return events


@pytest.mark.asyncio
async def test_events_map_and_stop_on_terminal(fake_redis):
    host = SessionHost(run_id=RUN)
    gate = ApprovalGate(
        gate_id="oq-1", kind="open_questions", node_id="ideation", title="Open questions — x", questions=["Q1?"]
    )
    await _seed(
        fake_redis,
        host,
        NodeStarted(node_id="ideation"),
        GateOpened(gate=gate),
        NodeCompleted(node_id="ideation"),
        RunClosed(outcome="succeeded", pr_url="http://pr"),
    )
    kinds = [e.kind async for e in RunStateTail(fake_redis, RUN).events(last_seen=0)]
    assert kinds == ["node_changed", "gate_opened", "node_changed", "run_closed"]


@pytest.mark.asyncio
async def test_snapshot_frame_when_last_seen_is_none(fake_redis):
    host = SessionHost(run_id=RUN)
    await _seed(fake_redis, host, NodeStarted(node_id="ideation"))
    tail = RunStateTail(fake_redis, RUN)
    events = await _collect(tail.events(last_seen=None), 1)
    assert len(events) == 1 and events[0].kind == "snapshot"
    await tail.close()


@pytest.mark.asyncio
async def test_resume_skips_already_seen(fake_redis):
    host = SessionHost(run_id=RUN)
    env1 = host.apply(NodeStarted(node_id="ideation"))
    await fake_redis.xadd(_key(), {"envelope": env1.model_dump_json()})
    env2 = host.apply(NodeCompleted(node_id="ideation"))
    await fake_redis.xadd(_key(), {"envelope": env2.model_dump_json()})
    env3 = host.apply(RunClosed(outcome="succeeded"))
    await fake_redis.xadd(_key(), {"envelope": env3.model_dump_json()})

    events = [e async for e in RunStateTail(fake_redis, RUN).events(last_seen=env1.server_seq)]
    assert [e.seq for e in events] == [env2.server_seq, env3.server_seq]


@pytest.mark.asyncio
async def test_gate_resolved_carries_answers(fake_redis):
    host = SessionHost(run_id=RUN)
    gate = ApprovalGate(
        gate_id="oq-2", kind="open_questions", node_id="ideation", title="Open questions — y", questions=["Q1?"]
    )
    await _seed(
        fake_redis,
        host,
        GateOpened(gate=gate),
        GateResolved(gate_id="oq-2", resolution="approved", resolved_by="u", answers={"Q1?": "A1"}),
    )
    tail = RunStateTail(fake_redis, RUN)
    events = await _collect(tail.events(last_seen=0), 2)
    resolved = [e for e in events if e.kind == "gate_resolved"][0]
    assert resolved.gate is not None and resolved.gate.answers == {"Q1?": "A1"}
    await tail.close()


def test_frame_to_event_skips_dispatch_frames():
    frame = {"event_kind": "action", "payload": {"server_seq": 5, "action": {"type": "dispatch/delta"}}}
    assert _frame_to_event(RUN, frame) is None


@pytest.mark.asyncio
async def test_backoff_recovers_after_one_failure(fake_redis, monkeypatch):
    host = SessionHost(run_id=RUN)
    await _seed(fake_redis, host, NodeStarted(node_id="ideation"), RunClosed(outcome="succeeded"))

    real_xrange = fake_redis.xrange
    calls = {"n": 0}

    async def _flaky_xrange(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("simulated redis blip")
        return await real_xrange(*args, **kwargs)

    monkeypatch.setattr(fake_redis, "xrange", _flaky_xrange)
    import parrot.integrations.devloop.tail as tail_mod

    # Bound the real backoff sleep to a few ms so the test stays fast.
    monkeypatch.setattr(tail_mod, "_MAX_BACKOFF", 0.01)

    kinds = [e.kind async for e in RunStateTail(fake_redis, RUN).events(last_seen=0)]
    assert kinds == ["node_changed", "run_closed"]
    assert calls["n"] >= 2
