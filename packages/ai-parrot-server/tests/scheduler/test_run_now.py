"""Tests for scheduler run-now + last-execution-result (FEAT-467 TASK-2520).

Two layers:

- ``TestManagerRunNow`` — a REAL ``AgentSchedulerManager`` with a real
  in-memory APScheduler (``start_headless(register_listeners=True)``,
  same path the standalone daemon uses), a fake agent/bot_manager, and a
  mocked DB layer (``get_schedule``/``AgentSchedule.get`` patched — no
  real Postgres). Proves run-now genuinely executes the SAME
  ``_execute_agent_job`` code path as a scheduled run, including the
  ``job_success`` listener's ``last_run``/``run_count``/``last_result``
  stamping.
- ``TestHandlerDispatch`` — ``SchedulerJobsHandler``/
  ``SchedulerLastResultHandler`` unit tests with a mocked manager,
  proving the HTTP-level action dispatch and exception-to-status mapping
  (including the existing pause/resume/update actions are untouched).
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from parrot.handlers.scheduler import SchedulerJobsHandler, SchedulerLastResultHandler
from parrot.scheduler import manager as manager_module
from parrot.scheduler.manager import AgentSchedulerManager, SchedulerRunNowConflictError
from parrot.scheduler.sanitize import SchedulerConfigError


def _unwrap(method):
    while hasattr(method, "__wrapped__"):
        method = method.__wrapped__
    return method


async def _decode(response: web.Response) -> dict:
    return json.loads(response.body)


def _make_fake_schedule(**overrides):
    base = {
        "schedule_id": "sched-1",
        "agent_name": "test_agent",
        "prompt": "do the thing",
        "method_name": None,
        "metadata": {},
        "is_crew": False,
        "send_result": {},
        "callbacks": [],
        "scheduler_type": "default",
        "last_run": None,
        "run_count": 0,
        "next_run": None,
        "enabled": True,
    }
    base.update(overrides)
    ns = SimpleNamespace(**base)
    ns.update = AsyncMock()
    return ns


class _FakeBot:
    def __init__(self):
        self.chat_calls: list[str] = []
        self.result = "ok-result"
        self.should_fail = False

    async def chat(self, prompt: str):
        self.chat_calls.append(prompt)
        if self.should_fail:
            raise RuntimeError("agent boom")
        return self.result


class _FakeBotManager:
    def __init__(self, bot: _FakeBot, agent_name: str = "test_agent"):
        self._bots = {agent_name: bot}
        self.registry = MagicMock()

    def get_crew(self, name):
        return None


class _FakePoolAcquireCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *_args):
        return False


class _FakePool:
    def __init__(self):
        self.conn = MagicMock()

    async def acquire(self):
        return _FakePoolAcquireCtx(self.conn)


# ---------------------------------------------------------------------------
# Real scheduler + mocked DB layer
# ---------------------------------------------------------------------------


class TestManagerRunNow:
    @pytest.fixture
    def fake_bot(self):
        return _FakeBot()

    @pytest.fixture
    async def manager(self, fake_bot, monkeypatch):
        mgr = AgentSchedulerManager(bot_manager=_FakeBotManager(fake_bot))
        # Start with no pool so start_headless() skips load_schedules_from_db()
        # (which would otherwise issue a real SQL query) — the fake pool is
        # only needed by run_schedule_now()/_update_schedule_run() afterwards.
        await mgr.start_headless(register_listeners=True)
        mgr._pool = _FakePool()
        yield mgr
        await mgr.stop_headless(wait=False)

    async def _wait_until(self, predicate, *, timeout: float = 3.0, interval: float = 0.05):
        elapsed = 0.0
        while not predicate() and elapsed < timeout:
            await asyncio.sleep(interval)
            elapsed += interval
        assert predicate(), "condition not met within timeout"

    @pytest.mark.asyncio
    async def test_run_now_executes_once(self, manager, fake_bot, monkeypatch):
        schedule = _make_fake_schedule()
        monkeypatch.setattr(manager, "get_schedule", AsyncMock(return_value=schedule))
        monkeypatch.setattr(manager_module.AgentSchedule, "get", AsyncMock(return_value=schedule))

        result_schedule = await manager.run_schedule_now(str(schedule.schedule_id))
        assert result_schedule is schedule

        await self._wait_until(lambda: len(fake_bot.chat_calls) >= 1)
        # Give the job_success -> _process_job_success task a beat to finish.
        await self._wait_until(lambda: schedule.run_count >= 1)

        assert fake_bot.chat_calls == ["do the thing"]
        assert len(fake_bot.chat_calls) == 1

    @pytest.mark.asyncio
    async def test_run_now_preserves_schedule_state(self, manager, fake_bot, monkeypatch):
        schedule = _make_fake_schedule(enabled=True, schedule_config_marker="untouched")
        monkeypatch.setattr(manager, "get_schedule", AsyncMock(return_value=schedule))
        monkeypatch.setattr(manager_module.AgentSchedule, "get", AsyncMock(return_value=schedule))

        await manager.run_schedule_now(str(schedule.schedule_id))
        await self._wait_until(lambda: schedule.run_count >= 1)

        # run_schedule_now/its completion path never touch these fields.
        assert schedule.enabled is True
        assert schedule.prompt == "do the thing"
        assert schedule.schedule_config_marker == "untouched"

    @pytest.mark.asyncio
    async def test_run_now_on_paused_job(self, manager, fake_bot, monkeypatch):
        """A disabled/paused schedule still runs once via run-now."""
        schedule = _make_fake_schedule(enabled=False)
        monkeypatch.setattr(manager, "get_schedule", AsyncMock(return_value=schedule))
        monkeypatch.setattr(manager_module.AgentSchedule, "get", AsyncMock(return_value=schedule))

        await manager.run_schedule_now(str(schedule.schedule_id))
        await self._wait_until(lambda: len(fake_bot.chat_calls) >= 1)

        assert schedule.enabled is False  # stays paused

    @pytest.mark.asyncio
    async def test_concurrent_run_now_409(self, manager, monkeypatch):
        schedule = _make_fake_schedule()
        monkeypatch.setattr(manager, "get_schedule", AsyncMock(return_value=schedule))
        monkeypatch.setattr(manager_module.AgentSchedule, "get", AsyncMock(return_value=schedule))

        await manager.run_schedule_now(str(schedule.schedule_id))
        with pytest.raises(SchedulerRunNowConflictError):
            await manager.run_schedule_now(str(schedule.schedule_id))

    @pytest.mark.asyncio
    async def test_last_result_populated(self, manager, fake_bot, monkeypatch):
        schedule = _make_fake_schedule()
        monkeypatch.setattr(manager, "get_schedule", AsyncMock(return_value=schedule))
        monkeypatch.setattr(manager_module.AgentSchedule, "get", AsyncMock(return_value=schedule))

        await manager.run_schedule_now(str(schedule.schedule_id))
        await self._wait_until(lambda: schedule.run_count >= 1)

        last_result = await manager.get_last_result(str(schedule.schedule_id))
        assert last_result["run_count"] == 1
        assert last_result["last_run"] is not None
        assert last_result["last_status"] == "success"
        assert last_result["last_result"] == "ok-result"

    @pytest.mark.asyncio
    async def test_last_result_populated_on_failure(self, manager, fake_bot, monkeypatch):
        fake_bot.should_fail = True
        schedule = _make_fake_schedule()
        monkeypatch.setattr(manager, "get_schedule", AsyncMock(return_value=schedule))
        monkeypatch.setattr(manager_module.AgentSchedule, "get", AsyncMock(return_value=schedule))

        await manager.run_schedule_now(str(schedule.schedule_id))
        await self._wait_until(lambda: schedule.run_count >= 1)

        last_result = await manager.get_last_result(str(schedule.schedule_id))
        assert last_result["last_status"] == "error"
        assert "agent boom" in last_result["last_error"]

    @pytest.mark.asyncio
    async def test_run_now_unknown_schedule_bubbles(self, manager, monkeypatch):
        monkeypatch.setattr(manager, "get_schedule", AsyncMock(side_effect=LookupError("no such schedule")))
        with pytest.raises(LookupError):
            await manager.run_schedule_now("does-not-exist")


# ---------------------------------------------------------------------------
# Handler-level dispatch (mocked manager)
# ---------------------------------------------------------------------------


def _make_handler(handler_cls, app, *, method="GET", path="/x", match_info=None, json_body=None):
    request = make_mocked_request(method, path, match_info=match_info or {}, app=app)
    if json_body is not None:
        request.json = AsyncMock(return_value=json_body)
    return handler_cls(request)


class TestHandlerDispatch:
    @pytest.fixture
    def fake_manager(self):
        manager = MagicMock()
        manager._serialize_job = MagicMock(return_value={"schedule_id": "sched-1"})
        manager.pause_schedule = AsyncMock(return_value=SimpleNamespace())
        manager.update_schedule = AsyncMock(return_value=SimpleNamespace())
        manager.run_schedule_now = AsyncMock(return_value=SimpleNamespace())
        manager.get_last_result = AsyncMock(
            return_value={
                "schedule_id": "sched-1",
                "last_run": None,
                "next_run": None,
                "run_count": 0,
                "last_status": None,
                "last_result": None,
                "last_result_time": None,
                "last_error": None,
                "last_error_time": None,
            }
        )
        return manager

    @pytest.fixture
    def app(self, fake_manager):
        application = web.Application()
        application["scheduler_manager"] = fake_manager
        return application

    @pytest.mark.asyncio
    async def test_patch_run_now_dispatches_to_manager(self, app, fake_manager):
        handler = _make_handler(
            SchedulerJobsHandler,
            app,
            method="PATCH",
            path="/schedules/sched-1",
            match_info={"schedule_id": "sched-1"},
            json_body={"action": "run_now"},
        )
        response = await handler.patch()
        assert response.status == 200
        fake_manager.run_schedule_now.assert_awaited_once_with("sched-1")

    @pytest.mark.asyncio
    async def test_patch_run_now_conflict_maps_to_409(self, app, fake_manager):
        fake_manager.run_schedule_now = AsyncMock(side_effect=SchedulerRunNowConflictError("already active"))
        handler = _make_handler(
            SchedulerJobsHandler,
            app,
            method="PATCH",
            path="/schedules/sched-1",
            match_info={"schedule_id": "sched-1"},
            json_body={"action": "run_now"},
        )
        response = await handler.patch()
        assert response.status == 409

    @pytest.mark.asyncio
    async def test_patch_pause_unchanged(self, app, fake_manager):
        handler = _make_handler(
            SchedulerJobsHandler,
            app,
            method="PATCH",
            path="/schedules/sched-1",
            match_info={"schedule_id": "sched-1"},
            json_body={"action": "pause"},
        )
        response = await handler.patch()
        assert response.status == 200
        fake_manager.pause_schedule.assert_awaited_once_with("sched-1")
        fake_manager.run_schedule_now.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_patch_resume_unchanged(self, app, fake_manager):
        handler = _make_handler(
            SchedulerJobsHandler,
            app,
            method="PATCH",
            path="/schedules/sched-1",
            match_info={"schedule_id": "sched-1"},
            json_body={"action": "resume"},
        )
        response = await handler.patch()
        assert response.status == 200
        fake_manager.update_schedule.assert_awaited_once_with("sched-1", {"enabled": True})

    @pytest.mark.asyncio
    async def test_patch_update_default_action_unchanged(self, app, fake_manager):
        payload = {"prompt": "new prompt"}
        handler = _make_handler(
            SchedulerJobsHandler,
            app,
            method="PATCH",
            path="/schedules/sched-1",
            match_info={"schedule_id": "sched-1"},
            json_body=payload,
        )
        response = await handler.patch()
        assert response.status == 200
        fake_manager.update_schedule.assert_awaited_once_with("sched-1", payload)

    @pytest.mark.asyncio
    async def test_patch_config_error_maps_to_400(self, app, fake_manager):
        fake_manager.update_schedule = AsyncMock(side_effect=SchedulerConfigError("bad config"))
        handler = _make_handler(
            SchedulerJobsHandler,
            app,
            method="PATCH",
            path="/schedules/sched-1",
            match_info={"schedule_id": "sched-1"},
            json_body={"foo": "bar"},
        )
        response = await handler.patch()
        assert response.status == 400

    @pytest.mark.asyncio
    async def test_last_result_handler_get(self, app, fake_manager):
        handler = _make_handler(
            SchedulerLastResultHandler,
            app,
            method="GET",
            path="/schedules/sched-1/last-result",
            match_info={"schedule_id": "sched-1"},
        )
        response = await handler.get()
        assert response.status == 200
        body = await _decode(response)
        assert body["status"] == "success"
        assert body["schedule_id"] == "sched-1"
        fake_manager.get_last_result.assert_awaited_once_with("sched-1")

    @pytest.mark.asyncio
    async def test_last_result_handler_missing_schedule_id(self, app):
        handler = _make_handler(
            SchedulerLastResultHandler,
            app,
            method="GET",
            path="/schedules//last-result",
            match_info={},
        )
        response = await handler.get()
        assert response.status == 400


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
