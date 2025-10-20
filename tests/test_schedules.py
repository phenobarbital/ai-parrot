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

from parrot.scheduler import AgentSchedulerManager
from parrot.scheduler.models import AgentSchedule


@pytest.mark.asyncio
async def test_schedule_creation(monkeypatch):
    """Test creating a schedule."""
    scheduler = AgentSchedulerManager()

    scheduler.setup(app=AsyncMock())

    scheduler._pool = DummyPool()
    monkeypatch.setattr(AgentSchedule, "save", AsyncMock())
    monkeypatch.setattr(AgentSchedule, "update", AsyncMock())
    scheduler.scheduler.add_job = AsyncMock(return_value=SimpleNamespace(next_run_time=None))

    schedule = await scheduler.add_schedule(
        agent_name="TestAgent",
        schedule_type="daily",
        schedule_config={"hour": 10, "minute": 0},
        prompt="Test prompt"
    )

    assert schedule.agent_name == "TestAgent"
    assert schedule.schedule_type == "daily"
    assert schedule.enabled is True
    assert schedule.is_crew is False
    assert schedule.send_result == {}


@pytest.mark.asyncio
async def test_execute_crew_job_uses_registered_crew(monkeypatch):
    """Ensure crew schedules resolve crews and forward metadata."""

    class DummyCrew:
        def __init__(self):
            self.calls = []

        async def run_sequential(self, query: str, agent_sequence=None):
            self.calls.append({
                'query': query,
                'agent_sequence': agent_sequence,
            })
            return {'status': 'ok'}

    class DummyRegistry:
        async def get_instance(self, _name):
            return None

    class DummyBotManager:
        def __init__(self, crew):
            self._bots = {}
            self.registry = DummyRegistry()
            self._crew_entry = (crew, SimpleNamespace(crew_id="crew-alpha"))

        def get_crew(self, identifier):
            if identifier == "CrewAlpha":
                return self._crew_entry
            return None

    crew = DummyCrew()
    scheduler = AgentSchedulerManager(bot_manager=DummyBotManager(crew))
    scheduler._update_schedule_run = AsyncMock()
    handle_mock = AsyncMock()
    monkeypatch.setattr(scheduler, "_handle_job_success", handle_mock)

    result = await scheduler._execute_agent_job(
        schedule_id="123",
        agent_name="CrewAlpha",
        prompt="Write the report",
        method_name="run_sequential",
        metadata={'agent_sequence': ['writer', 'editor']},
        is_crew=True,
        send_result={'recipients': ['user@example.com']},
    )

    assert result == {'status': 'ok'}
    assert crew.calls == [{
        'query': 'Write the report',
        'agent_sequence': ['writer', 'editor'],
    }]
    scheduler._update_schedule_run.assert_awaited_with("123", success=True)
    handle_mock.assert_awaited_once_with(
        "123",
        "CrewAlpha",
        {'status': 'ok'},
        None,
        {'recipients': ['user@example.com']},
    )


@pytest.mark.asyncio
async def test_handle_job_success_prefers_callback(monkeypatch):
    """Callbacks override default email notifications."""
    scheduler = AgentSchedulerManager()
    send_email_mock = AsyncMock()
    monkeypatch.setattr(scheduler, "_send_result_email", send_email_mock)

    observed = []

    async def callback(payload):
        observed.append(payload)

    await scheduler._handle_job_success(
        "abc",
        "Agent",
        {"value": 1},
        callback,
        {'recipients': ['user@example.com']},
    )

    assert observed == [{"value": 1}]
    send_email_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_job_success_sends_email_when_configured(monkeypatch):
    """Default success handling sends email when configured."""
    scheduler = AgentSchedulerManager()
    send_email_mock = AsyncMock()
    monkeypatch.setattr(scheduler, "_send_result_email", send_email_mock)

    await scheduler._handle_job_success(
        "abc",
        "Agent",
        {"value": 1},
        None,
        {'recipients': ['user@example.com']},
    )

    send_email_mock.assert_awaited_once_with(
        "abc",
        "Agent",
        {"value": 1},
        {'recipients': ['user@example.com']},
    )
