"""Tests for the async render job subsystem (FEAT-327, Module 4:
``RenderJobStore`` + the ``async=true`` dispatch branch / polling route).

Uses an injected in-memory Redis double (``_FakeRedis``) rather than a real
Redis connection — ``REDIS_HISTORY_URL`` points at a dev host unreachable
from this environment; "an injected fake" is explicitly sanctioned by
TASK-1891's own scope note.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web

from parrot.handlers.infographic import InfographicTalk
from parrot.handlers.infographic_render import RenderJob, RenderPayloadError
from parrot.handlers.render_jobs import (
    DEFAULT_MAX_RUNTIME_SECONDS,
    TERMINAL_JOB_TTL_SECONDS,
    RenderJobStore,
    resolve_max_runtime_seconds,
)
from parrot.models.infographic_templates import InfographicTemplate, infographic_registry
from parrot.tools.infographic_sections import SectionDescriptor, SectionSpec
from parrot.tools.infographic_toolkit import InfographicToolkit

TEMPLATE_NAME = "feat327_jobs_test_tpl"
TINY_TEMPLATE = (
    "<!doctype html><html><body>"
    '<script type="application/json" id="report-data">\n{}\n</script>'
    "</body></html>"
)


class _FakeRedis:
    """Minimal in-memory async Redis double (``set``/``get``/``expire`` only)."""

    def __init__(self) -> None:
        self._data: dict = {}
        self.expired: dict = {}

    async def set(self, key, value):
        self._data[key] = value

    async def get(self, key):
        return self._data.get(key)

    async def expire(self, key, seconds):
        self.expired[key] = seconds
        return True


def _job(status="pending", deadline=None) -> RenderJob:
    now = datetime.now(timezone.utc)
    return RenderJob(
        job_id="job-1",
        status=status,
        created_at=now.isoformat(),
        deadline=(deadline or now).isoformat(),
    )


# ---------------------------------------------------------------------------
# RenderJobStore unit tests
# ---------------------------------------------------------------------------

class TestJobStore:
    async def test_create_and_get_roundtrip(self):
        store = RenderJobStore(redis_client=_FakeRedis())
        job = _job()
        await store.create(job)
        fetched = await store.get("job-1")
        assert fetched is not None
        assert fetched.job_id == "job-1"
        assert fetched.status == "pending"

    async def test_terminal_state_sets_ttl(self):
        redis = _FakeRedis()
        store = RenderJobStore(redis_client=redis)
        job = _job()
        await store.create(job)
        done = job.model_copy(update={"status": "done"})
        await store.set_terminal(done)
        assert redis.expired[store._key("job-1")] == TERMINAL_JOB_TTL_SECONDS

    async def test_unknown_job_404_semantics(self):
        store = RenderJobStore(redis_client=_FakeRedis())
        assert await store.get("does-not-exist") is None

    async def test_multiworker_visibility(self):
        """A second store instance backed by the SAME redis client sees the job."""
        shared_redis = _FakeRedis()
        store_a = RenderJobStore(redis_client=shared_redis)
        store_b = RenderJobStore(redis_client=shared_redis)
        await store_a.create(_job())
        fetched = await store_b.get("job-1")
        assert fetched is not None
        assert fetched.job_id == "job-1"

    async def test_set_running_stamps_deadline(self):
        store = RenderJobStore(redis_client=_FakeRedis())
        await store.create(_job())
        before = datetime.now(timezone.utc)
        updated = await store.set_running("job-1", max_runtime_seconds=60)
        assert updated.status == "running"
        deadline = datetime.fromisoformat(updated.deadline)
        assert deadline > before

    async def test_set_running_unknown_job_raises(self):
        store = RenderJobStore(redis_client=_FakeRedis())
        with pytest.raises(KeyError):
            await store.set_running("nope")

    async def test_watchdog_flips_orphaned_running_to_failed(self):
        store = RenderJobStore(redis_client=_FakeRedis())
        past_deadline = datetime.now(timezone.utc) - timedelta(seconds=1)
        await store.create(_job(status="running", deadline=past_deadline))
        fetched = await store.get("job-1")
        assert fetched.status == "failed"
        assert fetched.error["code"] == "watchdog_timeout"

    async def test_watchdog_does_not_flip_running_before_deadline(self):
        store = RenderJobStore(redis_client=_FakeRedis())
        future_deadline = datetime.now(timezone.utc) + timedelta(seconds=60)
        await store.create(_job(status="running", deadline=future_deadline))
        fetched = await store.get("job-1")
        assert fetched.status == "running"

    async def test_watchdog_flips_orphaned_pending_to_failed(self):
        """A job whose task never even started (e.g. GC'd before its first
        await, or the worker died before set_running) is ALSO recovered —
        not just orphaned `running` jobs. Uses max_runtime_seconds=-1 (a
        deadline already in the past the instant it's stamped) since
        create() intentionally ALWAYS stamps a fresh deadline for pending
        jobs (see test_create_stamps_real_deadline_for_pending_jobs)."""
        store = RenderJobStore(redis_client=_FakeRedis())
        await store.create(_job(status="pending"), max_runtime_seconds=-1)
        fetched = await store.get("job-1")
        assert fetched.status == "failed"
        assert fetched.error["code"] == "watchdog_timeout"

    async def test_create_stamps_real_deadline_for_pending_jobs(self):
        """create() overrides a pending job's placeholder deadline with a
        REAL now+max_runtime one — a pending job must never be left with
        no effective watchdog coverage (it previously carried whatever
        placeholder the caller passed, often just `now`)."""
        store = RenderJobStore(redis_client=_FakeRedis())
        before = datetime.now(timezone.utc)
        # Deliberately pass an already-past placeholder deadline, like
        # _enqueue_render_job's `deadline=now.isoformat()` at creation time.
        await store.create(_job(status="pending", deadline=before))
        fetched = await store.get("job-1")
        assert fetched.status == "pending"  # NOT flipped — deadline was pushed into the future
        assert datetime.fromisoformat(fetched.deadline) > before

    def test_default_max_runtime_is_600s(self):
        assert DEFAULT_MAX_RUNTIME_SECONDS == 600
        assert resolve_max_runtime_seconds() == 600

    async def test_set_terminal_rejects_non_terminal_status(self):
        store = RenderJobStore(redis_client=_FakeRedis())
        with pytest.raises(ValueError):
            await store.set_terminal(_job(status="running"))

    async def test_set_terminal_refuses_to_overwrite_different_terminal_status(self):
        """The watchdog/own-completion race guard: a job already persisted
        as `failed` must not be silently overwritten with `done` (or vice
        versa) by a late-arriving terminal write."""
        store = RenderJobStore(redis_client=_FakeRedis())
        job = _job(status="running")
        await store.create(job)
        failed = job.model_copy(update={"status": "failed", "error": {"code": "x", "detail": "y"}})
        await store.set_terminal(failed)

        done = job.model_copy(update={"status": "done"})
        result = await store.set_terminal(done)

        assert result.status == "failed"  # existing terminal record wins
        fetched = await store.get("job-1")
        assert fetched.status == "failed"

    async def test_set_terminal_force_bypasses_the_guard(self):
        store = RenderJobStore(redis_client=_FakeRedis())
        job = _job(status="running")
        await store.create(job)
        failed = job.model_copy(update={"status": "failed", "error": {"code": "x", "detail": "y"}})
        await store.set_terminal(failed)

        done = job.model_copy(update={"status": "done"})
        result = await store.set_terminal(done, force=True)

        assert result.status == "done"
        fetched = await store.get("job-1")
        assert fetched.status == "done"


# ---------------------------------------------------------------------------
# Async dispatch branch tests (via InfographicTalk directly)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _register_test_template():
    infographic_registry.register(
        InfographicTemplate(name=TEMPLATE_NAME, description="FEAT-327 jobs test", block_specs=[])
    )
    yield
    infographic_registry._templates.pop(TEMPLATE_NAME, None)


@pytest.fixture
def fake_artifact_store():
    store = MagicMock()
    store.save_artifact = AsyncMock(return_value=None)
    store.get_public_url = AsyncMock(return_value="https://signed.example/artifact")
    return store


@pytest.fixture
def render_toolkit(fake_artifact_store):
    return InfographicToolkit(
        artifact_store=fake_artifact_store, templates={TEMPLATE_NAME: TINY_TEMPLATE}
    )


@pytest.fixture
def shared_redis():
    return _FakeRedis()


@pytest.fixture
def app(fake_artifact_store, render_toolkit, shared_redis):
    application = web.Application()
    application["artifact_store"] = fake_artifact_store
    application["infographic_render_toolkit"] = render_toolkit
    application["infographic_render_job_store"] = RenderJobStore(redis_client=shared_redis)
    return application


def _descriptor() -> SectionDescriptor:
    return SectionDescriptor(
        template=TEMPLATE_NAME,
        mode="data-splice",
        sections=[
            SectionSpec(
                name="hero", target="/hero", datasets=["revenue"],
                columns={"revenue": ["amount"]}, shape="records",
            )
        ],
    )


def _handler(app: web.Application) -> InfographicTalk:
    h = InfographicTalk.__new__(InfographicTalk)
    h.logger = logging.getLogger("test.render_jobs")
    h._request = MagicMock(app=app)
    return h


class TestAsyncBranch:
    async def test_202_and_poll_roundtrip(self, app):
        from parrot.handlers.infographic_render import decode_inline_datasets

        h = _handler(app)
        parsed = _fake_parsed(persist=True)
        frames = decode_inline_datasets(parsed)

        response = await h._enqueue_render_job(
            parsed, frames,
            user_id="u1", agent_id="a1", session_id="s1",
        )
        assert response.status == 202
        job_id = json.loads(response.body)["job_id"]

        # Let the fire-and-forget task run to completion.
        import asyncio
        for _ in range(50):
            job_store = h._get_render_job_store()
            job = await job_store.get(job_id)
            if job.status in ("done", "failed"):
                break
            await asyncio.sleep(0.01)

        assert job.status == "done", job.error
        assert job.result is not None
        assert job.result.persisted is True

    async def test_task_exception_becomes_failed(self, app, monkeypatch):
        h = _handler(app)

        async def _boom(*args, **kwargs):
            raise RenderPayloadError("hero", "boom")

        monkeypatch.setattr("parrot.handlers.infographic.render_deterministic", _boom)

        response = await h._enqueue_render_job(
            _fake_parsed(persist=True), {}, user_id="u1", agent_id="a1", session_id="s1",
        )
        job_id = json.loads(response.body)["job_id"]

        import asyncio
        job_store = h._get_render_job_store()
        for _ in range(50):
            job = await job_store.get(job_id)
            if job.status in ("done", "failed"):
                break
            await asyncio.sleep(0.01)

        assert job.status == "failed"
        assert job.error is not None
        assert "boom" in job.error["detail"]

    async def test_watchdog_flips_orphaned_running(self, app, shared_redis):
        job_store = RenderJobStore(redis_client=shared_redis)
        past_deadline = datetime.now(timezone.utc) - timedelta(seconds=1)
        await job_store.create(_job(status="running", deadline=past_deadline))

        h = _handler(app)
        response = await h._get_render_job_status("job-1")
        payload = json.loads(response.body)
        assert payload["status"] == "failed"
        assert payload["error"]["code"] == "watchdog_timeout"

    async def test_unknown_job_id_404(self, app):
        # BaseView.error() RAISES the HTTPException (aiohttp's dispatch layer
        # normally converts it to a response) — direct-call tests catch it.
        h = _handler(app)
        with pytest.raises(web.HTTPNotFound):
            await h._get_render_job_status("does-not-exist")


def _fake_parsed(*, persist: bool):
    from parrot.handlers.infographic_render import InlineDataset, RenderRequest

    return RenderRequest(
        datasets={"revenue": InlineDataset(orient="records", data=[{"amount": 1}])},
        template=TEMPLATE_NAME,
        descriptor=_descriptor(),
        persist=persist,
    )
