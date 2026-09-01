"""Unit tests for job handles for long-running agent methods (FEAT-477, TASK-2607)."""
import asyncio
import json
import time

import pytest
from parrot.auth.permission import PermissionContext, UserSession
from parrot.mcp.agent_jobs import AgentJobs, AgentJobStore


class _FakeRedis:
    """Minimal in-memory Redis double with a controllable virtual clock."""

    def __init__(self):
        self._data: dict[str, str] = {}
        self._expire_at: dict[str, float] = {}
        self._now = 0.0

    def now(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds
        self._sweep()

    def _sweep(self) -> None:
        expired = [k for k, deadline in self._expire_at.items() if self._now >= deadline]
        for k in expired:
            self._data.pop(k, None)
            self._expire_at.pop(k, None)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self._data[key] = value
        self._expire_at[key] = self._now + ttl

    async def get(self, key: str) -> "str | None":
        self._sweep()
        return self._data.get(key)

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)
        self._expire_at.pop(key, None)

    def tombstone_exists(self, job_id: str) -> bool:
        self._sweep()
        return f"mcp:agent-job:{job_id}:tombstone" in self._data


@pytest.fixture
def fake_redis():
    return _FakeRedis()


@pytest.fixture
def store(fake_redis):
    return AgentJobStore(fake_redis, clock=fake_redis.now)


def _pctx(user_id: str = "user-1", tenant_id: str = "acme") -> PermissionContext:
    return PermissionContext(
        session=UserSession(user_id=user_id, tenant_id=tenant_id, roles=frozenset())
    )


@pytest.fixture
def pctx():
    return _pctx()


@pytest.fixture
def other_pctx():
    return _pctx(user_id="user-2", tenant_id="acme")


def _sync_fast_resolver(agent_name: str, tool_name: str):
    async def _method(**kwargs):
        return {"forecast": kwargs.get("q", "x"), "series": list(range(50))}

    return _method


@pytest.fixture
def jobs(store):
    return AgentJobs(store, method_resolver=_sync_fast_resolver)


@pytest.fixture
async def completed_job(jobs, pctx):
    job_id = await jobs.start("finance", "long_forecast", {"q": "x"}, pctx)
    # Let the background task (a fast, non-blocking fake resolver) run to completion.
    for _ in range(50):
        status = await jobs.status(job_id, pctx)
        if status["status"] in ("succeeded", "failed"):
            break
        await asyncio.sleep(0)
    return job_id


class TestAgentJobs:
    async def test_start_returns_job_id_immediately(self, jobs, pctx):
        t0 = time.monotonic()
        job_id = await jobs.start("finance", "long_forecast", {}, pctx)
        assert job_id and (time.monotonic() - t0) < 1.0

    async def test_status_and_result_are_manifests(self, jobs, completed_job, pctx):
        res = await jobs.result(completed_job, pctx)
        assert res["status"] == "succeeded"
        assert "manifest" in res
        assert "raw" not in res
        assert len(json.dumps(res)) < 10_000

    async def test_job_scoped_to_principal(self, jobs, completed_job, other_pctx):
        assert await jobs.result(completed_job, other_pctx) is None
        assert await jobs.status(completed_job, other_pctx) is None

    async def test_ttl_expiry_reports_expired(self, store, fake_redis, pctx):
        """A job stuck in `pending`/`running` past its TTL reports `expired`."""
        never_resolves = asyncio.Event()

        def stuck_resolver(agent_name: str, tool_name: str):
            async def _method(**kwargs):
                await never_resolves.wait()

            return _method

        stuck_jobs = AgentJobs(store, method_resolver=stuck_resolver)
        job_id = await stuck_jobs.start("finance", "f", {}, pctx, ttl=1)
        fake_redis.advance(2)
        status = await stuck_jobs.status(job_id, pctx)
        assert status["status"] == "expired"

    async def test_delete_leaves_tombstone(self, jobs, completed_job, fake_redis, pctx):
        await jobs.delete(completed_job)
        assert fake_redis.tombstone_exists(completed_job)
        assert await jobs.status(completed_job, pctx) is None

    async def test_no_method_resolver_fails_the_job(self, store, pctx):
        jobs_without_resolver = AgentJobs(store, method_resolver=None)
        job_id = await jobs_without_resolver.start("finance", "f", {}, pctx)
        for _ in range(50):
            status = await jobs_without_resolver.status(job_id, pctx)
            if status["status"] == "failed":
                break
            await asyncio.sleep(0)
        result = await jobs_without_resolver.result(job_id, pctx)
        assert result["status"] == "failed"
        assert result["error"]

    async def test_missing_job_returns_none(self, jobs, pctx):
        assert await jobs.status("does-not-exist", pctx) is None
        assert await jobs.result("does-not-exist", pctx) is None
