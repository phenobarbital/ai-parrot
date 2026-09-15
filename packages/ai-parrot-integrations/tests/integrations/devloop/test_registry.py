"""Tests for RunRegistry (TASK-3203)."""

from __future__ import annotations

import time

import pytest

from parrot.integrations.devloop.models import Requester, RunRecord
from parrot.integrations.devloop.registry import RunRegistry


def _rec(run_id="run-1", actor_user="U1", phase="running") -> RunRecord:
    return RunRecord(
        run_id=run_id,
        kind="bug",
        title="t",
        channel_id="C1",
        phase=phase,
        started_at=time.time(),
        requester=Requester(transport="slack", tenant_id="T", user_id=actor_user),
    )


@pytest.mark.asyncio
async def test_roundtrip_and_live(fake_redis):
    reg = RunRegistry(fake_redis, retention_seconds=60)
    await reg.save(_rec())
    fresh = RunRegistry(fake_redis, retention_seconds=60)  # simulates a restarted bot
    assert (await fresh.get("run-1")).run_id == "run-1"
    assert [r.run_id for r in await fresh.live()] == ["run-1"]


@pytest.mark.asyncio
async def test_mark_terminal_expires_and_leaves_live_set(fake_redis):
    reg = RunRegistry(fake_redis, retention_seconds=60)
    await reg.save(_rec())
    await reg.mark_terminal("run-1")
    assert await reg.live() == []
    assert fake_redis.expirations["devloop:runs:run-1"] == 60


@pytest.mark.asyncio
async def test_terminal_record_not_added_to_live_set(fake_redis):
    reg = RunRegistry(fake_redis, retention_seconds=60)
    await reg.save(_rec(phase="completed"))
    assert await reg.live() == []


@pytest.mark.asyncio
async def test_list_for_filters_by_actor(fake_redis):
    reg = RunRegistry(fake_redis, retention_seconds=60)
    await reg.save(_rec(run_id="run-1", actor_user="U1"))
    await reg.save(_rec(run_id="run-2", actor_user="U2"))
    matches = await reg.list_for("slack:T:U1")
    assert [r.run_id for r in matches] == ["run-1"]


@pytest.mark.asyncio
async def test_save_redis_error_still_updates_memory(fake_redis, monkeypatch):
    reg = RunRegistry(fake_redis, retention_seconds=60)

    async def _boom(*args, **kwargs):
        raise ConnectionError("redis is down")

    monkeypatch.setattr(fake_redis, "hset", _boom)
    await reg.save(_rec())  # must not raise
    assert (await reg.get("run-1")).run_id == "run-1"


@pytest.mark.asyncio
async def test_get_unknown_run_returns_none(fake_redis):
    reg = RunRegistry(fake_redis, retention_seconds=60)
    assert await reg.get("no-such-run") is None
