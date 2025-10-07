import pytest
from unittest.mock import AsyncMock
from parrot.scheduler import AgentSchedulerManager


@pytest.mark.asyncio
async def test_schedule_creation():
    """Test creating a schedule."""
    scheduler = AgentSchedulerManager()

    scheduler.setup(app=AsyncMock())

    schedule = await scheduler.add_schedule(
        agent_name="TestAgent",
        schedule_type="daily",
        schedule_config={"hour": 10, "minute": 0},
        prompt="Test prompt"
    )

    assert schedule.agent_name == "TestAgent"
    assert schedule.schedule_type == "daily"
    assert schedule.enabled is True
