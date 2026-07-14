"""End-to-end integration tests for FEAT-147 crew result storage backends.

These tests exercise the full path from AgentCrew/AgentsFlow through
PersistenceMixin to each backend. All underlying drivers are mocked so no
real Postgres, Redis, or DocumentDB connection is opened.

``TestFeat306EndToEnd`` (bottom of file) covers the FEAT-306 per-agent
persistence + ``CrewExecutionDocument`` reconstruction path end-to-end,
using ``parrot.bots.flows.crew.crew.AgentCrew`` (the current, non-legacy
import path) and a fake in-memory ``ResultStorage`` — no external DB.
"""
from __future__ import annotations

import asyncio
import types
from collections import defaultdict
from typing import Any, Dict, List, Optional

import pytest
from unittest.mock import MagicMock

from parrot.bots.flows.core.result import FlowResult
from parrot.bots.flows.core.storage import CrewExecutionDocument
from parrot.bots.flows.core.storage.backends import ResultStorage
from parrot.bots.flows.crew.crew import AgentCrew


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


# ──────────────────────────────────────────────────────────────────────────────
# 7. FEAT-306 — per-agent persistence + CrewExecutionDocument e2e (TASK-1770)
# ──────────────────────────────────────────────────────────────────────────────


class _DummyToolManager:
    """Minimal ToolManager stand-in for crew tests."""

    def __init__(self) -> None:
        self._tools: Dict[str, Any] = {}

    def add_tool(self, tool: Any, tool_name: Optional[str] = None) -> None:
        name = tool_name or getattr(tool, "name", str(tool))
        self._tools[name] = tool

    def get_tool(self, tool_name: Optional[str]) -> Any:
        return self._tools.get(tool_name or "")

    def list_tools(self) -> List[str]:
        return list(self._tools.keys())


class _DummyAgent:
    """Deterministic agent stub for FEAT-306 e2e tests."""

    is_configured: bool = True
    EVENT_STATUS_CHANGED: str = "status_changed"
    EVENT_TASK_STARTED: str = "task_started"
    EVENT_TASK_COMPLETED: str = "task_completed"
    EVENT_TASK_FAILED: str = "task_failed"

    def __init__(self, name: str, response: str = "ok") -> None:
        self._name = name
        self._response = response
        self.tool_manager = _DummyToolManager()
        self.description = f"Agent {name}"
        self.prompts_received: List[str] = []

    @property
    def name(self) -> str:
        return self._name

    async def invoke(self, prompt: str, **kwargs: Any) -> Any:
        return await self.ask(question=prompt, **kwargs)

    async def ask(
        self, prompt: str = "", *, question: str = "", **kwargs: Any
    ) -> types.SimpleNamespace:
        effective_prompt = question or prompt
        self.prompts_received.append(effective_prompt)
        return types.SimpleNamespace(content=f"{self._response}: {effective_prompt[:40]}")

    def add_event_listener(self, event: str, handler: Any) -> None:
        """No-op for tests."""

    def as_tool(self, **kwargs: Any) -> None:
        return None

    async def configure(self) -> None:
        """No-op configure."""


class _FakeStorage(ResultStorage):
    """In-memory ResultStorage implementing both save() and fetch()."""

    def __init__(self) -> None:
        self.docs: Dict[str, list] = defaultdict(list)

    async def save(self, collection: str, document: dict) -> None:
        self.docs[collection].append(document)

    async def close(self) -> None:
        pass

    async def fetch(self, collection: str, execution_id: str) -> list:
        return [
            d for d in self.docs.get(collection, [])
            if d.get("execution_id") == execution_id
        ]


def _two_stub_agents() -> List[_DummyAgent]:
    return [_DummyAgent("a1", "first"), _DummyAgent("a2", "second")]


class TestFeat306EndToEnd:
    """E2E: crew run -> incremental writes + consolidated write -> fetch() ->
    from_storage() reconstruction equals from_memory() (spec §4 integration tests).
    """

    @pytest.mark.asyncio
    async def test_persist_and_reconstruct_roundtrip(self):
        fake_storage = _FakeStorage()
        crew = AgentCrew(
            name="e2e", agents=_two_stub_agents(), auto_configure=False,
            result_storage=fake_storage,
        )
        result = await crew.run_sequential("do the thing", generate_summary=False)
        await crew.aclose()
        eid = result.metadata["execution_id"]

        assert len(await fake_storage.fetch("crew_agent_results", eid)) == 2
        assert len(await fake_storage.fetch("crew_executions", eid)) == 1

        rebuilt = await CrewExecutionDocument.from_storage(fake_storage, eid)
        in_process = crew.build_execution_document()
        assert rebuilt is not None and in_process is not None
        # `timestamp` is excluded: `rebuilt` reflects the wall-clock time of
        # the original consolidated write, while `in_process` is rebuilt
        # fresh via a brand-new from_memory() call — the two inherently
        # differ by the (sub-millisecond) elapsed time between both calls.
        rebuilt_dict = rebuilt.to_dict()
        in_process_dict = in_process.to_dict()
        rebuilt_dict.pop("timestamp")
        in_process_dict.pop("timestamp")
        assert rebuilt_dict == in_process_dict

        md = rebuilt.to_markdown()
        assert "## Final Result" in md and "## Summary" in md
        assert "## Agent: A1" in md or "## Agent: a1" in md.lower() or "a1" in md.lower()

    @pytest.mark.asyncio
    async def test_aclose_drains_in_flight_agent_persist_tasks(self):
        fake_storage = _FakeStorage()
        crew = AgentCrew(
            name="e2e-drain", agents=_two_stub_agents(), auto_configure=False,
            result_storage=fake_storage,
        )
        await crew.run_sequential("task", generate_summary=False)
        await crew.aclose()

        assert crew._persist_tasks == set()
        # Everything scheduled must have landed before aclose() returned.
        assert len(fake_storage.docs["crew_agent_results"]) == 2
        assert len(fake_storage.docs["crew_executions"]) == 1

    @pytest.mark.asyncio
    async def test_storage_without_fetch_still_saves(self):
        """A ResultStorage subclass with only save()/close() (no fetch())
        still completes a run without errors — backward compat (spec G3)."""

        class WriteOnly(ResultStorage):
            def __init__(self) -> None:
                self.saved: list = []

            async def save(self, collection: str, document: dict) -> None:
                self.saved.append((collection, document))

            async def close(self) -> None:
                pass

        storage = WriteOnly()
        crew = AgentCrew(
            name="wo", agents=_two_stub_agents(), auto_configure=False,
            result_storage=storage,
        )
        result = await crew.run_sequential("x", generate_summary=False)
        await crew.aclose()

        assert isinstance(result, FlowResult)
        assert len(storage.saved) == 3  # 2 agent docs + 1 consolidated doc

    @pytest.mark.asyncio
    async def test_crash_case_agent_docs_only(self):
        """Simulate a crash-interrupted run: only per-agent docs were
        written (no consolidated doc) — from_storage() still reconstructs
        a document, ordered by per-agent timestamps."""
        from parrot.bots.flows.core.result import NodeResult

        fake_storage = _FakeStorage()
        node_a = NodeResult(node_id="a1", node_name="A1", task="t", result="r-a1")
        await fake_storage.save(
            "crew_agent_results",
            {
                "execution_id": "E1",
                "crew_name": "e2e",
                "method": "run_sequential",
                "node_id": "a1",
                "node_execution_id": node_a.execution_id,
                "timestamp": node_a.timestamp.timestamp(),
                "result": node_a.to_dict(),
            },
        )

        doc = await CrewExecutionDocument.from_storage(fake_storage, "E1")
        assert doc is not None
        assert doc.status == "partial"
        assert [a["node_id"] for a in doc.agent_results] == ["a1"]

    @pytest.mark.asyncio
    async def test_backward_compat_flowresult_unchanged(self):
        """Run modes still return FlowResult; result.output/.summary/.status
        behave as before (spec integration test)."""
        fake_storage = _FakeStorage()
        crew = AgentCrew(
            name="compat", agents=_two_stub_agents(), auto_configure=False,
            result_storage=fake_storage,
        )
        result = await crew.run_sequential("task", generate_summary=False)
        await crew.aclose()

        assert isinstance(result, FlowResult)
        assert result.output is not None
        assert result.summary == ""
        assert result.status in ("completed", "partial", "failed")
        assert hasattr(result, "agents")
        assert hasattr(result, "errors")
