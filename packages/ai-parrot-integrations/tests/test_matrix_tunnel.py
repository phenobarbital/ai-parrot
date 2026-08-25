"""Tests for AgentTunnel / TunnelRegistry — FEAT-463 TASK-2481."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.integrations.matrix.crew.config import TunnelConfig
from parrot.integrations.matrix.crew.tunnel import TunnelRegistry
from parrot.integrations.matrix.events import ParrotEventType, ResultEventContent

pytestmark = pytest.mark.asyncio


@pytest.fixture
def reg():
    svc = AsyncMock()
    svc.create_room_as_bot.return_value = "!tun:parrot.local"
    svc.list_agents = MagicMock(return_value={"a": "@parrot-a:parrot.local", "b": "@parrot-b:parrot.local"})
    svc.send_custom_event_as_agent.return_value = "$task"
    channels = MagicMock()
    channels._space_id = None
    return (
        TunnelRegistry(
            TunnelConfig(default_timeout=0.2, max_hops=2),
            svc,
            channels,
            wrappers={},
            server_name="parrot.local",
        ),
        svc,
    )


async def test_symmetric_lazy_creation(reg):
    r, svc = reg
    t1 = await r.get_or_create("a", "b")
    t2 = await r.get_or_create("b", "a")
    assert t1 is t2
    assert svc.create_room_as_bot.await_count == 1
    kw = svc.create_room_as_bot.call_args.kwargs
    assert kw["is_direct"] is True
    assert set(kw["invitees"]) == {"@parrot-a:parrot.local", "@parrot-b:parrot.local"}


async def test_ask_roundtrip(reg):
    r, svc = reg
    t = await r.get_or_create("a", "b")

    async def deliver():
        await asyncio.sleep(0.01)
        sent = svc.send_custom_event_as_agent.call_args.args[3]
        await r.on_custom_event(
            ParrotEventType.RESULT,
            ResultEventContent(
                task_id=sent["task_id"],
                content='{"answer": "42", "confidence": 0.8}',
                metadata={"correlation_id": sent["correlation_id"]},
            ).model_dump(),
            "!tun:parrot.local",
            "@parrot-b:parrot.local",
        )

    asyncio.create_task(deliver())
    ans = await t.ask("a", "b", "meaning?")
    assert ans.answer == "42"
    assert ans.confidence == 0.8
    assert ans.metadata["status"] == "ok"


async def test_ask_timeout(reg):
    r, _ = reg
    t = await r.get_or_create("a", "b")
    assert (await t.ask("a", "b", "q")).metadata["status"] == "timeout"


async def test_hop_limit(reg):
    r, svc = reg
    t = await r.get_or_create("a", "b")
    assert (await t.ask("a", "b", "q", hops=2)).metadata["status"] == "hop_limit"
    svc.send_custom_event_as_agent.assert_not_awaited()


async def test_schema_error(reg):
    r, svc = reg
    t = await r.get_or_create("a", "b")

    async def deliver():
        await asyncio.sleep(0.01)
        sent = svc.send_custom_event_as_agent.call_args.args[3]
        await r.on_custom_event(
            ParrotEventType.RESULT,
            ResultEventContent(
                task_id=sent["task_id"],
                content='{"answer": {"x": 1}}',
                metadata={"correlation_id": sent["correlation_id"]},
            ).model_dump(),
            "!tun:parrot.local",
            "@b:s",
        )

    asyncio.create_task(deliver())
    ans = await t.ask("a", "b", "q", expected_schema={"type": "object", "required": ["total"]})
    assert ans.metadata["status"] == "schema_error"


async def test_sweeper_tombstones_idle(reg):
    r, svc = reg
    t = await r.get_or_create("a", "b")
    t.last_used = datetime.now(timezone.utc) - timedelta(minutes=500)
    assert await r._sweep_once() == 1
    assert svc.leave_as_agent.await_count == 2
    assert any(c.args[1] == "m.room.tombstone" for c in svc.set_room_state_as_bot.await_args_list)
    assert not r.is_tunnel_room("!tun:parrot.local")


async def test_ttl_zero_never_sweeps(reg):
    r, svc = reg
    r.config.ttl_minutes = 0
    t = await r.get_or_create("a", "b")
    t.last_used = datetime.now(timezone.utc) - timedelta(days=30)
    assert await r._sweep_once() == 0
