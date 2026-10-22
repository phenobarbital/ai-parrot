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
    assert params == [
        "self",
        "job",
        "run_times",
    ], "apscheduler executor internals changed — revisit FEAT-631 coordination"


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
    assert isinstance(coord.build_fire_coordinator("none", use_redis=True), coord.RedisFireCoordinator)
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


def _patch_config(monkeypatch, values):
    class Config:
        def get(self, key):
            return values.get(key)

    monkeypatch.setattr("navconfig.config", Config())


def test_forced_redis_logs_warning(monkeypatch, caplog):
    _patch_config(monkeypatch, {})
    monkeypatch.setattr(coord.aioredis, "Redis", lambda **kwargs: FakeRedis())

    with caplog.at_level("WARNING", logger="Parrot.Scheduler.coordination"):
        result = coord.build_fire_coordinator("none", use_redis=True)

    assert isinstance(result, coord.RedisFireCoordinator)
    assert any("ignored" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_manager_prefix_namespaces_claim_keys(monkeypatch):
    _patch_config(monkeypatch, {})
    client = FakeRedis()
    monkeypatch.setattr(coord.aioredis, "Redis", lambda **kwargs: client)

    coordinator = coord.build_fire_coordinator(use_redis=True, prefix=coord.manager_prefix("x"))
    assert coordinator._prefix == "parrot:scheduler:x:"
    await coordinator.claim("job", datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert all(k.startswith("parrot:scheduler:x:fire:") for k in client.store)


def test_redis_db_env_and_fallback(monkeypatch):
    values = {}
    _patch_config(monkeypatch, values)

    assert coord.redis_db() == 6
    values["SCHEDULER_REDIS_DB"] = "3"
    assert coord.redis_db() == 3
    values["SCHEDULER_REDIS_DB"] = "99"
    assert coord.redis_db() == 6


@pytest.mark.asyncio
async def test_current_run_time_matches_claim(monkeypatch):
    claimed = []
    seen = []

    class Recording(coord.NullFireCoordinator):
        async def claim(self, job_id, run_time):
            claimed.append(run_time)
            return True

    async def fake_run(job, alias, run_times, logger_name):
        seen.append(coord.CURRENT_RUN_TIME.get())
        return []

    monkeypatch.setattr(coord, "run_coroutine_job", fake_run)
    executor = coord.CoordinatedAsyncIOExecutor(Recording())
    run_time = datetime(2026, 1, 1, tzinfo=timezone.utc)

    assert coord.CURRENT_RUN_TIME.get() is None
    await executor._claimed_run(_Job(), [run_time])

    assert seen == claimed == [run_time]
    assert coord.CURRENT_RUN_TIME.get() is None
