"""Agent/crew resolver and AgentSchedulerManager subclass tests (FEAT-644)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from parrot.scheduler.base import SchedulerManager, TargetRegistry
from parrot.scheduler.manager import (
    AgentResolver,
    AgentSchedulerManager,
    CrewResolver,
    ScheduleType,
    schedule,
    schedule_daily_report,
)
from parrot.scheduler.models import FireContext, JobDefinition


def _fire() -> FireContext:
    return FireContext.for_fire("s1", datetime(2026, 1, 1, tzinfo=timezone.utc))


def _definition(kind: str = "agent", **overrides: object) -> JobDefinition:
    data = {
        "schedule_id": "s1",
        "backend": "db",
        "target_kind": kind,
        "target_name": "target",
        "schedule_type": "interval",
        "schedule_config": {"minutes": 5},
    }
    data.update(overrides)
    return JobDefinition(**data)


class Agent:
    chatbot_id = "bot-1"

    async def chat(self, question: str) -> str:
        return question

    async def report(self, prompt: str, fire_id: str | None = None) -> str:
        return prompt

    async def _private(self) -> None:
        return None


class FakeRegistry:
    def __init__(self, instance: object | None = None, fail: bool = False) -> None:
        self.instance = instance
        self.fail = fail
        self.calls: list[str] = []

    async def get_instance(self, name: str) -> object | None:
        self.calls.append(name)
        if self.fail:
            raise RuntimeError("boom")
        return self.instance


class StubBotManager:
    """BotManager stub without a ``_bots`` attribute: any private read would fail."""

    def __init__(self, bots: dict | None = None, registry: FakeRegistry | None = None, crews: dict | None = None):
        self._public = bots or {}
        self.registry = registry or FakeRegistry()
        self._crews = crews or {}

    def get_bots(self) -> dict:
        return self._public

    async def get_crew(self, name: str, **_kw: object):
        return self._crews.get(name)


@pytest.mark.asyncio
async def test_agent_resolver_order() -> None:
    registered, listed, built = Agent(), Agent(), Agent()
    targets = TargetRegistry()
    registry = FakeRegistry(built)
    manager = StubBotManager({"b": listed}, registry)
    resolver = AgentResolver(targets, lambda: manager)

    assert await resolver.resolve("b") is listed
    assert registry.calls == []
    assert await resolver.resolve("c") is built
    assert registry.calls == ["c"]
    targets.register("a", registered, kind="agent")
    assert await resolver.resolve("a") is registered
    assert resolver.derive_target_id(registered) == "bot-1"
    assert not hasattr(manager, "_bots")


@pytest.mark.asyncio
async def test_agent_resolver_failures_return_none() -> None:
    resolver = AgentResolver(TargetRegistry(), lambda: StubBotManager(registry=FakeRegistry(fail=True)))
    assert await resolver.resolve("x") is None
    assert await AgentResolver(TargetRegistry(), lambda: None).resolve("x") is None


def test_agent_resolver_prompt_only_uses_chat() -> None:
    resolver = AgentResolver(TargetRegistry(), lambda: None)
    args, kwargs = resolver.build_call(Agent(), _definition(prompt="hello"), _fire())
    assert args == ["hello"]
    assert kwargs == {}


def test_agent_resolver_method_rules() -> None:
    resolver = AgentResolver(TargetRegistry(), lambda: None)
    with pytest.raises(ValueError, match="Either prompt or method_name"):
        resolver.build_call(Agent(), _definition(), _fire())
    with pytest.raises(ValueError, match="public"):
        resolver.build_call(Agent(), _definition(method_name="_private"), _fire())
    with pytest.raises(ValueError, match="not callable"):
        resolver.build_call(Agent(), _definition(method_name="missing"), _fire())
    _, kwargs = resolver.build_call(Agent(), _definition(method_name="report", prompt="p"), _fire())
    assert kwargs["prompt"] == "p"
    assert kwargs["fire_id"] == _fire().fire_id


@pytest.mark.asyncio
async def test_crew_resolver_awaits_get_crew() -> None:
    crew = object()
    crew_def = SimpleNamespace(crew_id="crew-9")
    manager = StubBotManager(crews={"c": (crew, crew_def)})
    resolver = CrewResolver(TargetRegistry(), lambda: manager)

    assert await resolver.resolve("c") is crew
    assert resolver.derive_target_id(crew) == "crew-9"
    assert await resolver.resolve("none") is None
    assert await CrewResolver(TargetRegistry(), lambda: None).resolve("c") is None


class Crew:
    async def run_flow(self, initial_task: str) -> None: ...
    async def run_loop(self, initial_task: str) -> None: ...
    async def run_sequential(self, query: str) -> None: ...
    async def run_parallel(self, tasks: list) -> None: ...
    async def other(self, text: str) -> None: ...


def test_crew_prompt_mapping() -> None:
    resolver = CrewResolver(TargetRegistry(), lambda: None)
    crew = Crew()
    for method, param in (("run_flow", "initial_task"), ("run_loop", "initial_task"), ("run_sequential", "query")):
        args, kwargs = resolver.build_call(crew, _definition("crew", method_name=method, prompt="go"), _fire())
        assert args == [] and kwargs[param] == "go"
    _, kwargs = resolver.build_call(crew, _definition("crew", method_name="other", prompt="go"), _fire())
    assert kwargs["text"] == "go"
    with pytest.raises(ValueError, match="method_name is required"):
        resolver.build_call(crew, _definition("crew", prompt="go"), _fire())


def test_agent_scheduler_manager_is_subclass() -> None:
    manager = AgentSchedulerManager(registered_name=f"agent-{uuid.uuid4().hex}")
    assert isinstance(manager, SchedulerManager)
    assert SchedulerManager.registered_name == "scheduler_manager"
    assert {"agent", "crew", "service"} <= set(manager._resolvers)


class ScheduledBot:
    name = "sbot"
    chatbot_id = "sbot"

    @schedule(schedule_type=ScheduleType.INTERVAL, minutes=5)
    async def poll(self) -> str:
        return "polled"

    @schedule_daily_report
    async def daily(self) -> str:
        return "daily"


@pytest.mark.asyncio
async def test_report_decorators_still_register(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SBOT_DAILY_REPORT", raising=False)
    manager = AgentSchedulerManager(registered_name=f"agent-{uuid.uuid4().hex}")
    bot = ScheduledBot()
    shared = dict(bot.daily._schedule_config)

    assert manager.register_bot_schedules(bot) == 2
    assert set(manager._code_jobs) == {"auto_sbot_poll", "auto_sbot_daily"}
    assert bot.daily._schedule_config == shared
    assert await manager._code_jobs["auto_sbot_daily"].method() == "daily"
    assert await manager._code_jobs["auto_sbot_poll"].method() == "polled"
