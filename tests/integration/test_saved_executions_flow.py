"""Integration tests for the AgentCrew Saved Crews flow (FEAT-307).

Exercises the full stack — ``PersistenceMixin._save_result()`` →
``ResultStorage`` → ``SavedExecutionService`` → replay through a real
``AgentCrew`` — against an in-memory ``ResultStorage`` implementation (no
real Postgres/Redis/DocumentDB backend required).
"""
import asyncio
import time
import uuid
from types import SimpleNamespace
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.bots.flows.core.storage.backends.base import ResultStorage
from parrot.bots.flows.crew import AgentCrew
from parrot.handlers.crew.models import ScheduleRequest
from parrot.handlers.crew.saved_execution_service import SavedExecutionService


# ---------------------------------------------------------------------------
# In-memory ResultStorage — no real database required
# ---------------------------------------------------------------------------


class InMemoryResultStorage(ResultStorage):
    """Minimal in-memory ``ResultStorage`` implementing all read/write methods.

    Mirrors the semantics of the real backends (TASK-1765/1768): ``tenant``
    defaults to ``"global"`` for legacy-style filtering, results are sorted
    newest-first, and ``get``/``delete`` operate on a generated ``id``.

    Partitioned by ``collection`` (like real tables/collections) — this
    matters once merged with FEAT-306's ``_save_agent_result()``, which
    writes to a separate ``crew_agent_results`` collection alongside the
    consolidated ``crew_executions`` record for the same run.
    """

    def __init__(self) -> None:
        self.records: dict[str, dict[str, dict[str, Any]]] = {}

    def _bucket(self, collection: str) -> dict[str, dict[str, Any]]:
        return self.records.setdefault(collection, {})

    async def save(self, collection: str, document: dict[str, Any]) -> None:
        record_id = str(uuid.uuid4())
        doc = dict(document)
        doc["id"] = record_id
        self._bucket(collection)[record_id] = doc

    async def list(
        self,
        collection: str,
        filters: Optional[dict[str, Any]] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        items = list(self._bucket(collection).values())
        filters = filters or {}
        if filters.get("tenant"):
            items = [i for i in items if i.get("tenant", "global") == filters["tenant"]]
        if filters.get("user_id"):
            items = [i for i in items if i.get("user_id") == filters["user_id"]]
        if filters.get("crew_name"):
            items = [i for i in items if i.get("crew_name") == filters["crew_name"]]
        if filters.get("method"):
            items = [i for i in items if i.get("method") == filters["method"]]
        items.sort(key=lambda d: d.get("timestamp", 0), reverse=True)
        return items[offset:offset + limit]

    async def get(self, collection: str, record_id: str) -> Optional[dict[str, Any]]:
        return self._bucket(collection).get(record_id)

    async def delete(self, collection: str, record_id: str) -> bool:
        bucket = self._bucket(collection)
        if record_id in bucket:
            del bucket[record_id]
            return True
        return False

    async def count(self, collection: str, filters: Optional[dict[str, Any]] = None) -> int:
        return len(await self.list(collection, filters, limit=10**9, offset=0))

    async def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_storage() -> InMemoryResultStorage:
    return InMemoryResultStorage()


def _fake_agent(name: str = "agent1") -> MagicMock:
    """Minimal fake agent driving a real AgentCrew execution (see TASK-1771)."""
    agent = MagicMock()
    agent.name = name
    agent.is_configured = True
    agent.description = "fake agent"
    agent.ask = AsyncMock(return_value=SimpleNamespace(content="agent output"))
    return agent


def _real_crew(storage: InMemoryResultStorage) -> AgentCrew:
    """A real AgentCrew wired to `storage`, so replay genuinely persists."""
    return AgentCrew(
        name="research-crew",
        agents=[_fake_agent()],
        persist_results=True,
        result_storage=storage,
    )


@pytest.fixture
def mock_bot_manager(mock_storage):
    """AsyncMock bot_manager resolving to a real AgentCrew wired to `mock_storage`."""
    bot_manager = AsyncMock()
    crew = _real_crew(mock_storage)
    crew_def = MagicMock()
    bot_manager.get_crew.return_value = (crew, crew_def)
    return bot_manager, crew


@pytest.fixture
def mock_scheduler_manager():
    scheduler_manager = AsyncMock()
    schedule = MagicMock()
    schedule.to_dict.return_value = {"schedule_id": "sched-1", "agent_name": "research-crew"}
    scheduler_manager.add_schedule.return_value = schedule
    return scheduler_manager


@pytest.fixture
def service(mock_storage, mock_bot_manager, mock_scheduler_manager):
    bot_manager, _ = mock_bot_manager
    return SavedExecutionService(
        storage=mock_storage,
        bot_manager=bot_manager,
        scheduler_manager=mock_scheduler_manager,
    )


async def _seed_execution(
    storage: InMemoryResultStorage,
    *,
    crew_name: str = "research-crew",
    method: str = "run_sequential",
    prompt: Optional[str] = "Analyze Q3 market trends",
    tenant: str = "acme",
    user_id: str = "user-001",
    timestamp: Optional[float] = None,
) -> str:
    """Save one execution document directly to storage and return its id."""
    doc = {
        "crew_name": crew_name,
        "method": method,
        "user_id": user_id,
        "session_id": "sess-abc",
        "tenant": tenant,
        "prompt": prompt,
        "timestamp": timestamp if timestamp is not None else time.time(),
        "result": {"raw": "Analysis complete..."},
    }
    before_ids = set(storage.records.get("crew_executions", {}).keys())
    await storage.save("crew_executions", doc)
    new_id = next(iter(set(storage.records["crew_executions"].keys()) - before_ids))
    return new_id


class TestSavedExecutionsFlow:
    @pytest.mark.asyncio
    async def test_save_and_list_roundtrip(self, service, mock_storage, mock_bot_manager):
        """Save via _save_result() with prompt/tenant, list via the service,
        and verify prompt is present."""
        _, crew = mock_bot_manager

        await crew._save_result(
            MagicMock(to_dict=lambda: {"raw": "ok"}),
            "run_sequential",
            user_id="user-001",
            session_id="sess-abc",
            prompt="Analyze Q3 market trends",
            tenant="acme",
        )

        items, total = await service.list_executions(tenant="acme", user_id="user-001")

        assert total == 1
        assert items[0]["prompt"] == "Analyze Q3 market trends"
        assert items[0]["tenant"] == "acme"

    @pytest.mark.asyncio
    async def test_replay_creates_new_execution(self, service, mock_storage, mock_bot_manager):
        """Replay an execution, verify a new execution record is saved.

        Note: replaying a real ``AgentCrew.run_sequential()`` also fires
        FEAT-306's ``_save_agent_result()`` once per completed agent, into
        the separate ``crew_agent_results`` collection — this test only
        asserts on the consolidated ``crew_executions`` collection that
        ``SavedExecutionService`` reads from.
        """
        _, crew = mock_bot_manager
        execution_id = await _seed_execution(mock_storage, user_id="user-001", tenant="acme")
        assert len(mock_storage.records["crew_executions"]) == 1

        result = await service.replay_execution(
            tenant="acme", user_id="user-001", execution_id=execution_id
        )
        # run_sequential's persist is fire-and-forget — await it before asserting.
        await asyncio.gather(*crew._persist_tasks, return_exceptions=True)

        assert result["status"] == "submitted"
        assert result["crew_name"] == "research-crew"
        assert len(mock_storage.records["crew_executions"]) == 2

    @pytest.mark.asyncio
    async def test_schedule_from_execution(self, service, mock_storage, mock_scheduler_manager):
        """Schedule a saved execution, verify AgentSchedule record created."""
        execution_id = await _seed_execution(mock_storage, user_id="user-001", tenant="acme")

        result = await service.schedule_execution(
            tenant="acme",
            user_id="user-001",
            execution_id=execution_id,
            schedule_config=ScheduleRequest(
                schedule_type="DAILY", schedule_config={"hour": 9, "minute": 0}
            ),
        )

        assert result == {"schedule_id": "sched-1", "agent_name": "research-crew"}
        mock_scheduler_manager.add_schedule.assert_awaited_once()
        _, kwargs = mock_scheduler_manager.add_schedule.await_args
        assert kwargs["is_crew"] is True
        assert kwargs["prompt"] == "Analyze Q3 market trends"

    @pytest.mark.asyncio
    async def test_tenant_isolation(self, service, mock_storage):
        """User A (tenant acme) cannot see user B's (tenant other) executions."""
        await _seed_execution(mock_storage, tenant="acme", user_id="user-001")
        await _seed_execution(mock_storage, tenant="other", user_id="user-002")

        items, total = await service.list_executions(tenant="acme", user_id="user-001")

        assert total == 1
        assert all(item["tenant"] == "acme" for item in items)

    @pytest.mark.asyncio
    async def test_pagination(self, service, mock_storage):
        """Verify offset/limit and total count correctness."""
        for i in range(5):
            await _seed_execution(
                mock_storage,
                tenant="acme",
                user_id="user-001",
                prompt=f"query {i}",
                timestamp=float(i),
            )

        items, total = await service.list_executions(
            tenant="acme", user_id="user-001", limit=2, offset=1
        )

        assert total == 5
        assert len(items) == 2
        # newest-first ordering: timestamps 4,3,2,1,0 — offset=1 skips ts=4
        assert items[0]["prompt"] == "query 3"
        assert items[1]["prompt"] == "query 2"

    @pytest.mark.asyncio
    async def test_replay_crew_not_found(self, service, mock_storage, mock_bot_manager):
        """Replay fails with ValueError when the crew no longer exists."""
        bot_manager, _ = mock_bot_manager
        bot_manager.get_crew.return_value = (None, None)
        execution_id = await _seed_execution(mock_storage, tenant="acme", user_id="user-001")

        with pytest.raises(ValueError, match="no longer exists"):
            await service.replay_execution(tenant="acme", user_id="user-001", execution_id=execution_id)

    @pytest.mark.asyncio
    async def test_replay_no_prompt(self, service, mock_storage):
        """Replay fails with ValueError when the original prompt is unavailable
        (legacy record saved before FEAT-307)."""
        execution_id = await _seed_execution(
            mock_storage, tenant="acme", user_id="user-001", prompt=None
        )

        with pytest.raises(ValueError, match="prompt not available"):
            await service.replay_execution(tenant="acme", user_id="user-001", execution_id=execution_id)

    @pytest.mark.asyncio
    async def test_get_execution_not_found(self, service, mock_storage):
        """get_execution returns None for a nonexistent execution id."""
        result = await service.get_execution(
            tenant="acme", user_id="user-001", execution_id="does-not-exist"
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_get_execution_wrong_tenant_returns_none(self, service, mock_storage):
        """get_execution returns None when tenant doesn't match the record's
        owner, even though the record genuinely exists — the sole enforcement
        point for ownership at the service layer (ResultStorage.get() has no
        SQL-level tenant/user_id scoping — see TASK-1768's Completion Note)."""
        execution_id = await _seed_execution(mock_storage, tenant="acme", user_id="user-001")

        result = await service.get_execution(
            tenant="other-tenant", user_id="user-001", execution_id=execution_id
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_get_execution_wrong_user_returns_none(self, service, mock_storage):
        """get_execution returns None when user_id doesn't match, same tenant."""
        execution_id = await _seed_execution(mock_storage, tenant="acme", user_id="user-001")

        result = await service.get_execution(
            tenant="acme", user_id="someone-else", execution_id=execution_id
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_delete_execution_wrong_tenant_leaves_record_intact(
        self, service, mock_storage
    ):
        """delete_execution refuses to delete a record belonging to a
        different tenant — verifies the record still exists afterward."""
        execution_id = await _seed_execution(mock_storage, tenant="acme", user_id="user-001")

        deleted = await service.delete_execution(
            tenant="other-tenant", user_id="user-001", execution_id=execution_id
        )

        assert deleted is False
        assert execution_id in mock_storage.records["crew_executions"]
