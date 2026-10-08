import asyncio
from datetime import datetime
from types import SimpleNamespace
import pytest
from unittest.mock import AsyncMock

pytest.importorskip("apscheduler")


class DummyAcquire:
    async def __aenter__(self):
        return AsyncMock()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class DummyPool:
    async def acquire(self):
        return DummyAcquire()


from parrot.scheduler import AgentSchedulerManager  # noqa: E402
from parrot.scheduler.models import FireContext, JobDefinition, ServiceSchedule  # noqa: E402


@pytest.mark.asyncio
async def test_schedule_creation(monkeypatch):
    """Test creating a schedule."""
    scheduler = AgentSchedulerManager()

    scheduler.setup(app=AsyncMock())

    scheduler._pool = DummyPool()
    scheduler.register_target("TestAgent", SimpleNamespace(chat=AsyncMock()), kind="agent")
    monkeypatch.setattr(ServiceSchedule, "save", AsyncMock())
    monkeypatch.setattr(ServiceSchedule, "update", AsyncMock())
    scheduler.scheduler.add_job = lambda *args, **kwargs: SimpleNamespace(next_run_time=None)

    schedule = await scheduler.add_schedule(
        target_kind="agent",
        target_name="TestAgent",
        schedule_type="daily",
        schedule_config={"hour": 10, "minute": 0},
        prompt="Test prompt",
    )

    assert schedule.target_name == "TestAgent"
    assert schedule.schedule_type == "daily"
    assert schedule.target_kind == "agent"
    assert schedule.send_result == {}


@pytest.mark.asyncio
async def test_execute_crew_job_uses_registered_crew(monkeypatch):
    """Ensure crew schedules resolve crews and forward metadata."""

    class DummyCrew:
        def __init__(self):
            self.calls = []

        async def run_sequential(self, query: str, agent_sequence=None):
            self.calls.append(
                {
                    "query": query,
                    "agent_sequence": agent_sequence,
                }
            )
            return {"status": "ok"}

    class DummyRegistry:
        async def get_instance(self, _name):
            return None

    class DummyBotManager:
        def __init__(self, crew):
            self._bots = {}
            self.registry = DummyRegistry()
            self._crew_entry = (crew, SimpleNamespace(crew_id="crew-alpha"))

        async def get_crew(self, identifier):
            if identifier == "CrewAlpha":
                return self._crew_entry
            return None

    crew = DummyCrew()
    scheduler = AgentSchedulerManager(bot_manager=DummyBotManager(crew))
    definition = JobDefinition(
        schedule_id="123",
        backend="db",
        target_kind="crew",
        target_name="CrewAlpha",
        prompt="Write the report",
        method_name="run_sequential",
        schedule_type="interval",
        schedule_config={"minutes": 5},
        metadata={"agent_sequence": ["writer", "editor"]},
        send_result={"recipients": ["user@example.com"]},
    )
    result = await scheduler._execute_job(definition, FireContext.for_fire("123", datetime.now().astimezone()))

    assert result == {"status": "ok"}
    assert crew.calls == [
        {
            "query": "Write the report",
            "agent_sequence": ["writer", "editor"],
        }
    ]


@pytest.mark.asyncio
async def test_handle_job_success_prefers_callback(monkeypatch):
    """Callbacks override default email notifications."""
    scheduler = AgentSchedulerManager()
    send_email_mock = AsyncMock()
    monkeypatch.setattr(scheduler, "_send_result_email", send_email_mock)

    observed = []

    async def callback(payload, **_kwargs):
        observed.append(payload)

    definition = JobDefinition(
        schedule_id="abc",
        backend="code",
        target_kind="agent",
        target_name="Agent",
        schedule_type="interval",
        schedule_config={"minutes": 5},
        send_result={"recipients": ["user@example.com"]},
    )
    await scheduler._handle_job_success(definition, {"value": 1}, callback)

    assert observed == [{"value": 1}]
    send_email_mock.assert_awaited_once_with(definition, {"value": 1}, {"recipients": ["user@example.com"]})


@pytest.mark.asyncio
async def test_handle_job_success_sends_email_when_configured(monkeypatch):
    """Default success handling sends email when configured."""
    scheduler = AgentSchedulerManager()
    send_email_mock = AsyncMock()
    monkeypatch.setattr(scheduler, "_send_result_email", send_email_mock)

    definition = JobDefinition(
        schedule_id="abc",
        backend="code",
        target_kind="agent",
        target_name="Agent",
        schedule_type="interval",
        schedule_config={"minutes": 5},
        send_result={"recipients": ["user@example.com"]},
    )
    await scheduler._handle_job_success(definition, {"value": 1}, None)

    send_email_mock.assert_awaited_once_with(
        definition,
        {"value": 1},
        {"recipients": ["user@example.com"]},
    )
