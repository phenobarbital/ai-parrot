"""Tests for the Roost blackboard (FEAT-747 TASK-4719)."""

import asyncio

import pytest

from parrot.bots.flows.core.context import FlowContext
from parrot.roost.blackboard import (
    InMemoryBlackboard,
    StaleWriteError,
    WriterDeniedError,
    WriterPolicy,
)
from parrot.roost.performatives import InteractionProtocol, Performative

pytestmark = pytest.mark.asyncio


@pytest.fixture
def bb():
    return InMemoryBlackboard(scope="chan", policy=WriterPolicy())


async def test_cas_and_stale(bb):
    e1 = await bb.put("roster", ["a"], writer="harness", expected_version=None)
    await bb.put("roster", ["a", "b"], writer="harness", expected_version=e1.version)
    with pytest.raises(StaleWriteError):
        await bb.put("roster", ["x"], writer="harness", expected_version=e1.version)
    entry = await bb.get("roster", reader="anyone")
    assert entry.value == ["a", "b"] and entry.version == 2


async def test_create_existing_is_stale(bb):
    await bb.put("tasks", {}, writer="engine", expected_version=None)
    with pytest.raises(StaleWriteError):
        await bb.put("tasks", {"x": 1}, writer="engine", expected_version=None)


async def test_single_writer_concurrent_and_inform_once(bb):
    got = []
    await bb.subscribe("tasks", lambda m: asyncio.sleep(0, got.append(m)), subscriber_name="s")
    await bb.put("tasks", {}, writer="engine", expected_version=None)
    res = await asyncio.gather(
        bb.put("tasks", 1, writer="engine", expected_version=1),
        bb.put("tasks", 2, writer="engine", expected_version=1),
        return_exceptions=True,
    )
    assert sum(isinstance(r, StaleWriteError) for r in res) == 1 and len(got) == 2
    assert all(m.performative == Performative.INFORM and m.protocol == InteractionProtocol.SUBSCRIBE for m in got)


async def test_failing_subscriber_does_not_block(bb):
    got = []

    async def bad(_m):
        raise RuntimeError("boom")

    await bb.subscribe("tasks", bad, subscriber_name="bad")
    await bb.subscribe("tasks", lambda m: asyncio.sleep(0, got.append(m)), subscriber_name="good")
    await bb.put("tasks", {}, writer="engine", expected_version=None)
    assert len(got) == 1


async def test_writer_denied(bb):
    with pytest.raises(WriterDeniedError):
        await bb.put("roster", [], writer="agent-a", expected_version=None)


async def test_digest_owner_moves_to_last_closer(bb):
    bb.policy.record_request_closed("agent-a")
    e = await bb.put("digest", "d1", writer="agent-a", expected_version=None)
    bb.policy.record_request_closed("agent-b")
    with pytest.raises(WriterDeniedError):
        await bb.put("digest", "d2", writer="agent-a", expected_version=e.version)
    e2 = await bb.put("digest", "d2", writer="agent-b", expected_version=e.version)
    assert e2.version == 2


async def test_digest_coordinator_owns():
    bb = InMemoryBlackboard(scope="c", policy=WriterPolicy(coordinator="coord"))
    bb.policy.record_request_closed("agent-a")
    with pytest.raises(WriterDeniedError):
        await bb.put("digest", "x", writer="agent-a", expected_version=None)
    await bb.put("digest", "x", writer="coord", expected_version=None)


async def test_unknown_key_first_writer(bb):
    await bb.put("notes", 1, writer="a", expected_version=None)
    with pytest.raises(WriterDeniedError):
        await bb.put("notes", 2, writer="b", expected_version=1)


async def test_render_prefix_stable(bb):
    await bb.put("tasks", {"b": 1, "a": 2}, writer="engine", expected_version=None)
    await bb.put("roster", ["x"], writer="harness", expected_version=None)
    r1 = bb.render_prefix(reader="r")
    r2 = bb.render_prefix(reader="r")
    assert r1 == r2
    assert r1.index("roster") < r1.index("tasks")
    assert '{"a": 2, "b": 1}' in r1


async def test_flow_context_blackboard_default_and_snapshot():
    ctx = FlowContext(initial_task="t")
    assert ctx.blackboard is None
    before = ctx.to_snapshot()
    ctx.blackboard = InMemoryBlackboard(scope="c", policy=WriterPolicy())
    after = ctx.to_snapshot()
    assert "blackboard" not in type(after).model_fields
    assert set(before.model_dump()) == set(after.model_dump())
    assert "blackboard" not in str(after.model_dump())
    assert ctx.shared_data == {}
