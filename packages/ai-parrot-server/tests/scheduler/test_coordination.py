"""Tests for parrot.scheduler.coordination (FEAT-631 TASK-4062)."""

import inspect
from datetime import datetime, timezone

import pytest
from apscheduler.executors.asyncio import AsyncIOExecutor

from parrot.scheduler import coordination as coord
from parrot.scheduler.sanitize import SchedulerConfigError


class FakeRedis:
    """Dict-backed async double for SET NX EX and DELETE."""

    def __init__(self, raise_on: bool = False):
        self.store: dict = {}
        self.raise_on = raise_on

    async def set(self, key, value, nx=False, ex=None):
        if self.raise_on:
            raise ConnectionError("redis down")
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def delete(self, key):
        self.store.pop(key, None)

    async def aclose(self):
        return None


def test_executor_hook_signature_guard():
    params = list(inspect.signature(AsyncIOExecutor._do_submit_job).parameters)
    assert params == ["self", "job", "run_times"], "apscheduler executor internals changed — revisit FEAT-631 coordination"


@pytest.mark.asyncio
async def test_claim_once_across_two_coordinators():
    client = FakeRedis()
    first = coord.RedisFireCoordinator(client, worker_id="one")
    second = coord.RedisFireCoordinator(client, worker_id="two")
    run_time = datetime(2026, 1, 1, tzinfo=timezone.utc)

    assert await first.claim("job", run_time)
    assert not await second.claim("job", run_time)
    assert await second.claim("job", run_time.replace(second=1))


@pytest.mark.asyncio
async def test_claim_redis_error_raises_coordination_error():
    coordinator = coord.RedisFireCoordinator(FakeRedis(raise_on=True))

    with pytest.raises(coord.FireCoordinationError):
        await coordinator.claim("job", datetime.now(timezone.utc))


@pytest.mark.asyncio
async def test_run_now_guard_cross_worker():
    client = FakeRedis()
    first = coord.RedisFireCoordinator(client, worker_id="one")
    second = coord.RedisFireCoordinator(client, worker_id="two")

    assert await first.try_acquire_running("schedule")
    assert not await second.try_acquire_running("schedule")
    await first.release_running("schedule")
    assert await second.try_acquire_running("schedule")


@pytest.mark.asyncio
async def test_null_coordinator_guard():
    coordinator = coord.NullFireCoordinator(worker_id="local")

    assert await coordinator.try_acquire_running("schedule")
    assert not await coordinator.try_acquire_running("schedule")
    await coordinator.release_running("schedule")
    assert await coordinator.try_acquire_running("schedule")


def test_build_fire_coordinator_modes(monkeypatch):
    values = {}

    class Config:
        def get(self, key):
            return values.get(key)

    monkeypatch.setattr("navconfig.config", Config())
    monkeypatch.setattr(coord.aioredis, "Redis", lambda **kwargs: FakeRedis())

    assert isinstance(coord.build_fire_coordinator(), coord.NullFireCoordinator)
    values["SCHEDULER_COORDINATION"] = "redis"
    assert isinstance(coord.build_fire_coordinator(), coord.RedisFireCoordinator)
    assert isinstance(coord.build_fire_coordinator("none", use_redis=True), coord.NullFireCoordinator)
    values["SCHEDULER_COORDINATION"] = "bogus"
    with pytest.raises(SchedulerConfigError):
        coord.build_fire_coordinator()
    values.clear()
    assert isinstance(coord.build_fire_coordinator(use_redis=True), coord.RedisFireCoordinator)


class _Job:
    id = "job"
    _jobstore_alias = "default"

    async def func(self):
        raise AssertionError("claimed job should not run")


@pytest.mark.asyncio
async def test_executor_lost_claim_dispatches_nothing():
    class LostCoordinator(coord.NullFireCoordinator):
        async def claim(self, job_id, run_time):
            return False

    executor = coord.CoordinatedAsyncIOExecutor(LostCoordinator())
    result = await executor._claimed_run(_Job(), [datetime.now(timezone.utc)])

    assert result == []


@pytest.mark.asyncio
async def test_executor_unavailable_fails_closed():
    unavailable = []

    async def on_unavailable(job_id, error):
        unavailable.append((job_id, error))

    class UnavailableCoordinator(coord.NullFireCoordinator):
        async def claim(self, job_id, run_time):
            raise coord.FireCoordinationError("redis down")

    executor = coord.CoordinatedAsyncIOExecutor(UnavailableCoordinator(), on_unavailable=on_unavailable)
    result = await executor._claimed_run(_Job(), [datetime.now(timezone.utc)])

    assert result == []
    assert len(unavailable) == 1
    assert unavailable[0][0] == "job"
    assert isinstance(unavailable[0][1], coord.FireCoordinationError)
