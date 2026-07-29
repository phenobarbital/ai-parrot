"""Unit tests for SavedExecutionService (FEAT-307)."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.handlers.crew.models import ExecutionFilter, ScheduleRequest
from parrot.handlers.crew.saved_execution_service import SavedExecutionService


@pytest.fixture
def mock_storage():
    storage = AsyncMock()
    storage.list.return_value = [
        {"id": "abc", "crew_name": "test", "prompt": "query", "tenant": "acme", "user_id": "u1"}
    ]
    storage.get.return_value = {
        "id": "abc",
        "crew_name": "test",
        "prompt": "query",
        "method": "run_sequential",
        "tenant": "acme",
        "user_id": "u1",
    }
    storage.count.return_value = 1
    storage.delete.return_value = True
    return storage


@pytest.fixture
def mock_bot_manager():
    bot_manager = AsyncMock()
    crew = MagicMock()
    crew.agents = {"agent1": MagicMock()}
    crew.run_sequential = AsyncMock(return_value=MagicMock(to_dict=lambda: {"output": "ok"}))
    crew_def = MagicMock()
    bot_manager.get_crew.return_value = (crew, crew_def)
    return bot_manager, crew


@pytest.fixture
def mock_scheduler_manager():
    scheduler_manager = AsyncMock()
    schedule = MagicMock()
    schedule.to_dict.return_value = {"schedule_id": "sched-1", "agent_name": "test"}
    scheduler_manager.add_schedule.return_value = schedule
    return scheduler_manager


class TestSavedExecutionService:
    @pytest.mark.asyncio
    async def test_list_executions(self, mock_storage):
        """list_executions delegates to storage with correct filters."""
        service = SavedExecutionService(storage=mock_storage)

        items, total = await service.list_executions(
            tenant="acme", user_id="u1", filters=ExecutionFilter(crew_name="test")
        )

        assert items == mock_storage.list.return_value
        assert total == 1
        list_filters = mock_storage.list.await_args.args[1]
        assert list_filters["tenant"] == "acme"
        assert list_filters["user_id"] == "u1"
        assert list_filters["crew_name"] == "test"
        count_filters = mock_storage.count.await_args.args[1]
        assert count_filters["tenant"] == "acme"

    @pytest.mark.asyncio
    async def test_get_execution(self, mock_storage):
        """get_execution delegates to storage and verifies tenant/user ownership."""
        service = SavedExecutionService(storage=mock_storage)

        result = await service.get_execution(tenant="acme", user_id="u1", execution_id="abc")

        assert result == mock_storage.get.return_value
        mock_storage.get.assert_awaited_once_with("crew_executions", "abc")

    @pytest.mark.asyncio
    async def test_get_execution_wrong_tenant_returns_none(self, mock_storage):
        """get_execution returns None when the record belongs to another tenant."""
        service = SavedExecutionService(storage=mock_storage)

        result = await service.get_execution(tenant="other-tenant", user_id="u1", execution_id="abc")

        assert result is None

    @pytest.mark.asyncio
    async def test_replay_success(self, mock_storage, mock_bot_manager):
        """replay resolves crew and calls run_sequential."""
        bot_manager, crew = mock_bot_manager
        service = SavedExecutionService(storage=mock_storage, bot_manager=bot_manager)

        result = await service.replay_execution(tenant="acme", user_id="u1", execution_id="abc")

        assert result["crew_name"] == "test"
        assert result["method"] == "run_sequential"
        assert result["status"] == "submitted"
        assert "job_id" in result
        crew.run_sequential.assert_awaited_once_with(query="query", user_id="u1")

    @pytest.mark.asyncio
    async def test_replay_crew_not_found(self, mock_storage):
        """replay raises ValueError when crew not found."""
        bot_manager = AsyncMock()
        bot_manager.get_crew.return_value = (None, None)
        service = SavedExecutionService(storage=mock_storage, bot_manager=bot_manager)

        with pytest.raises(ValueError, match="no longer exists"):
            await service.replay_execution(tenant="acme", user_id="u1", execution_id="abc")

    @pytest.mark.asyncio
    async def test_replay_no_prompt(self, mock_storage, mock_bot_manager):
        """replay raises ValueError when prompt is None."""
        mock_storage.get.return_value = {
            "id": "abc",
            "crew_name": "test",
            "prompt": None,
            "method": "run_sequential",
            "tenant": "acme",
            "user_id": "u1",
        }
        bot_manager, _ = mock_bot_manager
        service = SavedExecutionService(storage=mock_storage, bot_manager=bot_manager)

        with pytest.raises(ValueError, match="prompt not available"):
            await service.replay_execution(tenant="acme", user_id="u1", execution_id="abc")

    @pytest.mark.asyncio
    async def test_replay_execution_not_found(self, mock_storage, mock_bot_manager):
        """replay raises ValueError when the execution record doesn't exist."""
        mock_storage.get.return_value = None
        bot_manager, _ = mock_bot_manager
        service = SavedExecutionService(storage=mock_storage, bot_manager=bot_manager)

        with pytest.raises(ValueError, match="not found"):
            await service.replay_execution(tenant="acme", user_id="u1", execution_id="missing")

    @pytest.mark.asyncio
    async def test_replay_run_loop_unsupported(self, mock_storage, mock_bot_manager):
        """replay raises ValueError for run_loop (condition can't be reconstructed)."""
        mock_storage.get.return_value = {
            "id": "abc",
            "crew_name": "test",
            "prompt": "query",
            "method": "run_loop",
            "tenant": "acme",
            "user_id": "u1",
        }
        bot_manager, _ = mock_bot_manager
        service = SavedExecutionService(storage=mock_storage, bot_manager=bot_manager)

        with pytest.raises(ValueError, match="Cannot replay method 'run_loop'"):
            await service.replay_execution(tenant="acme", user_id="u1", execution_id="abc")

    @pytest.mark.asyncio
    async def test_replay_run_parallel_broadcasts_prompt(self, mock_storage, mock_bot_manager):
        """replay of run_parallel broadcasts the saved prompt to every agent."""
        mock_storage.get.return_value = {
            "id": "abc",
            "crew_name": "test",
            "prompt": "query",
            "method": "run_parallel",
            "tenant": "acme",
            "user_id": "u1",
        }
        bot_manager, crew = mock_bot_manager
        crew.run_parallel = AsyncMock(return_value=MagicMock(to_dict=lambda: {"output": "ok"}))
        service = SavedExecutionService(storage=mock_storage, bot_manager=bot_manager)

        result = await service.replay_execution(tenant="acme", user_id="u1", execution_id="abc")

        assert result["method"] == "run_parallel"
        crew.run_parallel.assert_awaited_once_with(
            tasks=[{"agent_id": "agent1", "query": "query"}], user_id="u1"
        )

    @pytest.mark.asyncio
    async def test_schedule_execution(self, mock_storage, mock_scheduler_manager):
        """schedule calls AgentSchedulerManager.add_schedule with is_crew=True."""
        service = SavedExecutionService(
            storage=mock_storage, scheduler_manager=mock_scheduler_manager
        )
        schedule_request = ScheduleRequest(
            schedule_type="DAILY", schedule_config={"hour": 9, "minute": 0}
        )

        result = await service.schedule_execution(
            tenant="acme", user_id="u1", execution_id="abc", schedule_config=schedule_request
        )

        assert result == {"schedule_id": "sched-1", "agent_name": "test"}
        _, kwargs = mock_scheduler_manager.add_schedule.await_args
        assert mock_scheduler_manager.add_schedule.await_args.args[0] == "test"
        assert mock_scheduler_manager.add_schedule.await_args.args[1] == "DAILY"
        assert kwargs["is_crew"] is True
        assert kwargs["prompt"] == "query"

    @pytest.mark.asyncio
    async def test_schedule_execution_no_scheduler_manager(self, mock_storage):
        """schedule_execution raises ValueError when no scheduler_manager is configured."""
        service = SavedExecutionService(storage=mock_storage)
        schedule_request = ScheduleRequest(schedule_type="DAILY", schedule_config={"hour": 9})

        with pytest.raises(ValueError, match="No scheduler manager configured"):
            await service.schedule_execution(
                tenant="acme", user_id="u1", execution_id="abc", schedule_config=schedule_request
            )

    @pytest.mark.asyncio
    async def test_delete_execution(self, mock_storage):
        """delete delegates to storage.delete."""
        service = SavedExecutionService(storage=mock_storage)

        result = await service.delete_execution(tenant="acme", user_id="u1", execution_id="abc")

        assert result is True
        mock_storage.delete.assert_awaited_once_with("crew_executions", "abc")

    @pytest.mark.asyncio
    async def test_delete_execution_not_found(self, mock_storage):
        """delete_execution returns False when the record doesn't exist."""
        mock_storage.get.return_value = None
        service = SavedExecutionService(storage=mock_storage)

        result = await service.delete_execution(tenant="acme", user_id="u1", execution_id="missing")

        assert result is False
        mock_storage.delete.assert_not_awaited()
