"""End-to-end integration tests for FEAT-147 crew result storage backends.

These tests exercise the full path from AgentCrew/AgentsFlow through
PersistenceMixin to each backend. All underlying drivers are mocked so no
real Postgres, Redis, or DocumentDB connection is opened.
"""
from __future__ import annotations

import asyncio

import pytest
from unittest.mock import MagicMock

from parrot.bots.flows.core.storage.backends import ResultStorage


# ──────────────────────────────────────────────────────────────────────────────
# 1. Default backend is DocumentDB
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_default_backend_is_documentdb(monkeypatch, mock_documentdb):
    """No storage params + no env var → exactly one DocumentDb write."""
    monkeypatch.setattr(
        "parrot.bots.flows.core.storage.backends.factory.CREW_RESULT_STORAGE",
        "documentdb",
    )
    from parrot.bots.orchestration.crew import AgentCrew

    docdb_cls, instance = mock_documentdb
    crew = AgentCrew(name="default-test")
    await crew._save_result(MagicMock(to_dict=lambda: {"x": 1}), "run_flow")
    docdb_cls.assert_called_once()
    instance.write.assert_awaited_once()
    await crew.aclose()


# ──────────────────────────────────────────────────────────────────────────────
# 2. Global env var routes to Postgres
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_global_env_var_routes_to_postgres(
    monkeypatch, mock_asyncdb_pg, mock_documentdb
):
    """CREW_RESULT_STORAGE=postgres (no constructor args) routes to Postgres."""
    monkeypatch.setattr(
        "parrot.bots.flows.core.storage.backends.factory.CREW_RESULT_STORAGE",
        "postgres",
    )
    from parrot.bots.orchestration.crew import AgentCrew

    pg_cls, conn = mock_asyncdb_pg
    docdb_cls, _ = mock_documentdb

    crew = AgentCrew(name="env-test")
    await crew._save_result(MagicMock(to_dict=lambda: {"y": 2}), "run_flow")

    pg_cls.assert_called_once()
    docdb_cls.assert_not_called()
    await crew.aclose()


# ──────────────────────────────────────────────────────────────────────────────
# 3. persist_results=False opens no connection at all
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_persist_results_false_opens_no_connection(
    monkeypatch, mock_documentdb, mock_asyncdb_pg, mock_asyncdb_redis
):
    """persist_results=False → no driver constructor ever invoked."""
    from parrot.bots.orchestration.crew import AgentCrew

    docdb_cls, _ = mock_documentdb
    pg_cls, _ = mock_asyncdb_pg
    redis_cls, _ = mock_asyncdb_redis

    crew = AgentCrew(name="opt-out", persist_results=False)
    await crew._save_result(MagicMock(to_dict=lambda: {"a": 1}), "run_flow")

    docdb_cls.assert_not_called()
    pg_cls.assert_not_called()
    redis_cls.assert_not_called()


# ──────────────────────────────────────────────────────────────────────────────
# 4. async with releases storage connection
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_async_with_releases_connection(mock_asyncdb_pg):
    """Exiting async with block triggers exactly one close() on the backend."""
    from parrot.bots.orchestration.crew import AgentCrew

    _, conn = mock_asyncdb_pg

    async with AgentCrew(name="lifecycle-test", result_storage="postgres") as crew:
        await crew._save_result(MagicMock(to_dict=lambda: {}), "run_flow")

    conn.close.assert_awaited_once()


# ──────────────────────────────────────────────────────────────────────────────
# 5. Pending persist tasks complete before close
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pending_persist_tasks_complete_before_close():
    """aclose() awaits all in-flight slow saves before invoking storage.close()."""
    from parrot.bots.orchestration.crew import AgentCrew

    completed: list = []

    class _SlowStorage(ResultStorage):
        async def save(self, collection: str, document: dict) -> None:
            await asyncio.sleep(0.01)
            completed.append(document)

        async def close(self) -> None:
            pass

    crew = AgentCrew(name="slow-save-test", result_storage=_SlowStorage())

    # Schedule two slow saves and register them on _persist_tasks
    for i in range(2):
        t = asyncio.get_running_loop().create_task(
            crew._save_result(MagicMock(to_dict=lambda: {"i": i}), "run_flow")
        )
        crew._persist_tasks.add(t)
        t.add_done_callback(crew._persist_tasks.discard)

    # aclose() must wait for both tasks
    await crew.aclose()
    assert len(completed) == 2


# ──────────────────────────────────────────────────────────────────────────────
# 6. AgentsFlow with redis backend writes one key
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_agentsflow_redis_backend_writes_key(mock_asyncdb_redis):
    """AgentsFlow(result_storage='redis')._save_result() issues one Redis SET."""
    from parrot.bots.flow.fsm import AgentsFlow

    _, conn = mock_asyncdb_redis

    flow = AgentsFlow(name="redis-flow-test", result_storage="redis")
    await flow._save_result(MagicMock(to_dict=lambda: {"z": 3}), "run_flow")

    conn.execute.assert_awaited_once()
    # First positional arg to execute() is the Redis command
    call_args = conn.execute.call_args
    assert call_args.args[0] == "SET"
    # Key format: crew_executions:<name>:<timestamp_ms>
    key: str = call_args.args[1]
    assert key.startswith("crew_executions:redis-flow-test:")

    await flow.aclose()
