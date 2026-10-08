"""Run-now and last-result tests for the target-agnostic scheduler API."""

from __future__ import annotations

import asyncio
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from parrot.handlers.scheduler import SchedulerJobsHandler, SchedulerLastResultHandler
from parrot.scheduler.base import SchedulerRunNowConflictError, SchedulerUnavailableError
from parrot.scheduler.manager import AgentSchedulerManager
from parrot.scheduler.models import JobDefinition, RunState
from parrot.scheduler.runstate import MemoryRunState
from parrot.scheduler.sanitize import SchedulerConfigError


async def _decode(response: web.Response) -> dict:
    return json.loads(response.body)


def _definition(*, schedule_id: str | None = None) -> JobDefinition:
    return JobDefinition(
        schedule_id=schedule_id or str(uuid.uuid4()),
        backend="db",
        target_kind="agent",
        target_name="test_agent",
        prompt="do the thing",
        schedule_type="interval",
        schedule_config={"minutes": 5},
    )


class _FakeBot:
    def __init__(self) -> None:
        self.chat_calls: list[str] = []
        self.result = "ok-result"
        self.should_fail = False

    async def chat(self, prompt: str) -> str:
        self.chat_calls.append(prompt)
        if self.should_fail:
            raise RuntimeError("agent boom")
        return self.result


class _FakeBotManager:
    def __init__(self, bot: _FakeBot) -> None:
        self._bots = {"test_agent": bot}
        self.registry = MagicMock()

    def get_bots(self) -> dict[str, _FakeBot]:
        return self._bots

    async def get_crew(self, _name: str) -> None:
        return None


class TestManagerRunNow:
    @pytest.fixture
    async def manager(self, monkeypatch: pytest.MonkeyPatch):
        bot = _FakeBot()
        instance = AgentSchedulerManager(bot_manager=_FakeBotManager(bot))
        instance._memory_state = MemoryRunState("db")
        monkeypatch.setattr(instance, "_run_state_for", lambda _backend: instance._memory_state)
        await instance.start_headless(register_listeners=True)
        yield instance, bot
        await instance.stop_headless(wait=False)

    async def _wait_for_state(self, state: MemoryRunState, schedule_id: str) -> RunState:
        for _ in range(60):
            result = await state.read(schedule_id)
            if result is not None and result.run_count:
                return result
            await asyncio.sleep(0.05)
        pytest.fail("run-now did not finish")

    @pytest.mark.asyncio
    async def test_run_now_executes_once(self, manager, monkeypatch: pytest.MonkeyPatch) -> None:
        instance, bot = manager
        definition = _definition()
        stored = SimpleNamespace(_jobstore_alias="default", enabled=True)
        monkeypatch.setattr(instance, "_locate", AsyncMock(return_value=("db", definition, stored)))
        monkeypatch.setattr(instance, "get_schedule", AsyncMock(return_value=definition))
        assert await instance.run_schedule_now(definition.schedule_id) is definition
        state = await self._wait_for_state(instance._memory_state, definition.schedule_id)
        assert bot.chat_calls == ["do the thing"]
        assert state.last_status == "success"
        assert state.last_result == "ok-result"

    @pytest.mark.asyncio
    async def test_run_now_preserves_definition(self, manager, monkeypatch: pytest.MonkeyPatch) -> None:
        instance, bot = manager
        definition = _definition()
        stored = SimpleNamespace(_jobstore_alias="default", enabled=True)
        original = definition.model_dump()
        monkeypatch.setattr(instance, "_locate", AsyncMock(return_value=("db", definition, stored)))
        monkeypatch.setattr(instance, "get_schedule", AsyncMock(return_value=definition))
        await instance.run_schedule_now(definition.schedule_id)
        await self._wait_for_state(instance._memory_state, definition.schedule_id)
        assert definition.model_dump() == original
        assert bot.chat_calls == ["do the thing"]

    @pytest.mark.asyncio
    async def test_concurrent_run_now_409(self, manager, monkeypatch: pytest.MonkeyPatch) -> None:
        instance, _ = manager
        definition = _definition()
        stored = SimpleNamespace(_jobstore_alias="default", enabled=True)
        monkeypatch.setattr(instance, "_locate", AsyncMock(return_value=("db", definition, stored)))
        monkeypatch.setattr(instance, "get_schedule", AsyncMock(return_value=definition))
        await instance.run_schedule_now(definition.schedule_id)
        with pytest.raises(SchedulerRunNowConflictError):
            await instance.run_schedule_now(definition.schedule_id)

    @pytest.mark.asyncio
    async def test_last_result_populated_on_failure(self, manager, monkeypatch: pytest.MonkeyPatch) -> None:
        instance, bot = manager
        bot.should_fail = True
        definition = _definition()
        stored = SimpleNamespace(_jobstore_alias="default", enabled=True)
        monkeypatch.setattr(instance, "_locate", AsyncMock(return_value=("db", definition, stored)))
        monkeypatch.setattr(instance, "get_schedule", AsyncMock(return_value=definition))
        await instance.run_schedule_now(definition.schedule_id)
        state = await self._wait_for_state(instance._memory_state, definition.schedule_id)
        assert state.last_status == "error"
        assert "agent boom" in (state.last_error or "")


def _make_handler(handler_cls, app, *, method="GET", match_info=None, json_body=None):
    request = make_mocked_request(method, "/x", match_info=match_info or {}, app=app)
    if json_body is not None:
        request.json = AsyncMock(return_value=json_body)
    return handler_cls(request)


class TestHandlerDispatch:
    @pytest.fixture
    def fake_manager(self):
        manager = MagicMock()
        manager._serialize_job = MagicMock(return_value={"schedule_id": "sched-1", "backend": "db"})
        manager.pause_schedule = AsyncMock(return_value=_definition(schedule_id="sched-1"))
        manager.update_schedule = AsyncMock(return_value=_definition(schedule_id="sched-1"))
        manager.run_schedule_now = AsyncMock(return_value=_definition(schedule_id="sched-1"))
        manager.get_last_result = AsyncMock(return_value=RunState(schedule_id="sched-1", backend="db", enabled=True))
        return manager

    @pytest.fixture
    def app(self, fake_manager):
        application = web.Application()
        application["scheduler_manager"] = fake_manager
        return application

    @pytest.mark.asyncio
    async def test_patch_run_now_dispatches_to_manager(self, app, fake_manager) -> None:
        response = await _make_handler(
            SchedulerJobsHandler,
            app,
            method="PATCH",
            match_info={"schedule_id": "sched-1"},
            json_body={"action": "run_now"},
        ).patch()
        assert response.status == 200
        fake_manager.run_schedule_now.assert_awaited_once_with("sched-1")

    @pytest.mark.asyncio
    async def test_patch_run_now_conflict_maps_to_409(self, app, fake_manager) -> None:
        fake_manager.run_schedule_now = AsyncMock(side_effect=SchedulerRunNowConflictError("already active"))
        response = await _make_handler(
            SchedulerJobsHandler,
            app,
            method="PATCH",
            match_info={"schedule_id": "sched-1"},
            json_body={"action": "run_now"},
        ).patch()
        assert response.status == 409

    @pytest.mark.asyncio
    async def test_patch_run_now_unavailable_maps_to_503(self, app, fake_manager) -> None:
        fake_manager.run_schedule_now = AsyncMock(side_effect=SchedulerUnavailableError("coordination unavailable"))
        response = await _make_handler(
            SchedulerJobsHandler,
            app,
            method="PATCH",
            match_info={"schedule_id": "sched-1"},
            json_body={"action": "run_now"},
        ).patch()
        assert response.status == 503

    @pytest.mark.asyncio
    async def test_patch_pause_unchanged(self, app, fake_manager) -> None:
        response = await _make_handler(
            SchedulerJobsHandler,
            app,
            method="PATCH",
            match_info={"schedule_id": "sched-1"},
            json_body={"action": "pause"},
        ).patch()
        assert response.status == 200
        fake_manager.pause_schedule.assert_awaited_once_with("sched-1")

    @pytest.mark.asyncio
    async def test_patch_update_error_maps_to_400(self, app, fake_manager) -> None:
        fake_manager.update_schedule = AsyncMock(side_effect=SchedulerConfigError("bad config"))
        response = await _make_handler(
            SchedulerJobsHandler,
            app,
            method="PATCH",
            match_info={"schedule_id": "sched-1"},
            json_body={"prompt": "new"},
        ).patch()
        assert response.status == 400

    @pytest.mark.asyncio
    async def test_last_result_handler_get(self, app, fake_manager) -> None:
        response = await _make_handler(SchedulerLastResultHandler, app, match_info={"schedule_id": "sched-1"}).get()
        assert response.status == 200
        assert (await _decode(response))["schedule_id"] == "sched-1"
