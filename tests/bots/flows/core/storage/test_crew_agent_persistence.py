"""AgentCrew wiring tests for per-agent persistence + consolidated document
(TASK-1769, FEAT-306).

Uses local stub agents (mirroring packages/ai-parrot/tests/_crew_test_helpers.py's
DummyAgent, duplicated here to stay self-contained under the root tests/ tree)
and a fake in-memory ResultStorage.
"""
from __future__ import annotations

import types
from collections import defaultdict
from typing import Any, Dict, List, Optional

import pytest

from parrot.bots.flows.core.storage.backends import ResultStorage
from parrot.bots.flows.crew.crew import AgentCrew


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
    """Deterministic agent stub for AgentCrew wiring tests."""

    is_configured: bool = True
    EVENT_STATUS_CHANGED: str = "status_changed"
    EVENT_TASK_STARTED: str = "task_started"
    EVENT_TASK_COMPLETED: str = "task_completed"
    EVENT_TASK_FAILED: str = "task_failed"

    def __init__(self, name: str, response: str = "ok", *, fail: bool = False) -> None:
        self._name = name
        self._response = response
        self._fail = fail
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
        if self._fail:
            raise RuntimeError(f"{self._name} failed")
        return types.SimpleNamespace(content=f"{self._response}: {effective_prompt[:40]}")

    def add_event_listener(self, event: str, handler: Any) -> None:
        """No-op for tests."""

    def as_tool(self, **kwargs: Any) -> None:
        return None

    async def configure(self) -> None:
        """No-op configure."""


class _FakeStorage(ResultStorage):
    """In-memory ResultStorage capturing save() calls, per-collection."""

    def __init__(self) -> None:
        self.docs: Dict[str, list] = defaultdict(list)

    async def save(self, collection: str, document: dict) -> None:
        self.docs[collection].append(document)

    async def close(self) -> None:
        pass


def _two_agents() -> List[_DummyAgent]:
    return [_DummyAgent("a1", "first"), _DummyAgent("a2", "second")]


class TestRunSequentialWiring:
    @pytest.mark.asyncio
    async def test_stamps_unique_execution_id(self):
        # Two separate crew instances (not two runs on the same instance) —
        # AgentCrew's FSM nodes are not reset between separate top-level
        # run_sequential() calls on the same instance, a pre-existing
        # limitation unrelated to FEAT-306.
        crew1 = AgentCrew(
            name="c", agents=_two_agents(), auto_configure=False,
            result_storage=_FakeStorage(),
        )
        crew2 = AgentCrew(
            name="c", agents=_two_agents(), auto_configure=False,
            result_storage=_FakeStorage(),
        )
        result1 = await crew1.run_sequential("task", generate_summary=False)
        result2 = await crew2.run_sequential("task", generate_summary=False)
        await crew1.aclose()
        await crew2.aclose()

        assert "execution_id" in result1.metadata
        assert "execution_id" in result2.metadata
        assert result1.metadata["execution_id"] != result2.metadata["execution_id"]

    @pytest.mark.asyncio
    async def test_persists_one_doc_per_agent(self):
        storage = _FakeStorage()
        crew = AgentCrew(
            name="c", agents=_two_agents(), auto_configure=False,
            result_storage=storage,
        )
        result = await crew.run_sequential("task", generate_summary=False)
        await crew.aclose()

        agent_docs = storage.docs["crew_agent_results"]
        assert len(agent_docs) == 2
        eid = result.metadata["execution_id"]
        assert all(d["execution_id"] == eid for d in agent_docs)
        assert {d["node_id"] for d in agent_docs} == {"a1", "a2"}

    @pytest.mark.asyncio
    async def test_consolidated_doc_written_with_agent_results(self):
        storage = _FakeStorage()
        crew = AgentCrew(
            name="c", agents=_two_agents(), auto_configure=False,
            result_storage=storage,
        )
        await crew.run_sequential("task", generate_summary=False)
        await crew.aclose()

        crew_docs = storage.docs["crew_executions"]
        assert len(crew_docs) == 1
        assert crew_docs[0]["result"]["agent_results"]
        assert len(crew_docs[0]["result"]["agent_results"]) == 2

    @pytest.mark.asyncio
    async def test_persist_agent_results_false(self):
        storage = _FakeStorage()
        crew = AgentCrew(
            name="c", agents=_two_agents(), auto_configure=False,
            result_storage=storage, persist_agent_results=False,
        )
        await crew.run_sequential("task", generate_summary=False)
        await crew.aclose()

        assert storage.docs["crew_agent_results"] == []
        assert len(storage.docs["crew_executions"]) == 1

    @pytest.mark.asyncio
    async def test_persist_results_false_writes_nothing(self):
        storage = _FakeStorage()
        crew = AgentCrew(
            name="c", agents=_two_agents(), auto_configure=False,
            result_storage=storage, persist_results=False,
        )
        await crew.run_sequential("task", generate_summary=False)
        await crew.aclose()

        assert storage.docs["crew_agent_results"] == []
        assert storage.docs["crew_executions"] == []

    @pytest.mark.asyncio
    async def test_build_execution_document_roundtrip(self):
        storage = _FakeStorage()
        crew = AgentCrew(
            name="c", agents=_two_agents(), auto_configure=False,
            result_storage=storage,
        )
        result = await crew.run_sequential("task", generate_summary=False)
        await crew.aclose()

        doc = crew.build_execution_document()
        assert doc is not None
        assert doc.execution_id == result.metadata["execution_id"]
        assert len(doc.agent_results) == 2

    @pytest.mark.asyncio
    async def test_build_execution_document_none_before_any_run(self):
        crew = AgentCrew(
            name="c", agents=_two_agents(), auto_configure=False,
            result_storage=_FakeStorage(),
        )
        assert crew.build_execution_document() is None


class TestRunLoopWiring:
    # NOTE: `crew.workflow_graph = {}` sidesteps a PRE-EXISTING bug (verified
    # present before this feature's changes via `git stash`, unrelated to
    # FEAT-306) where run_loop's "fresh FSM per iteration" reassignment
    # (`node.fsm = AgentTaskMachine(...)`) raises a pydantic "frozen
    # instance" ValidationError because CrewAgentNode is a frozen model.
    # Clearing workflow_graph makes every `self.workflow_graph.get(agent_id)`
    # lookup return None, so run_loop skips FSM handling entirely while
    # still exercising the real execution_id / persistence wiring under test.

    @pytest.mark.asyncio
    async def test_persists_one_doc_per_agent_per_iteration(self):
        storage = _FakeStorage()
        crew = AgentCrew(
            name="c", agents=[_DummyAgent("a1", "ok")], auto_configure=False,
            result_storage=storage,
        )
        crew.workflow_graph = {}
        result = await crew.run_loop(
            "start", condition="", max_iterations=2, generate_summary=False,
        )
        await crew.aclose()

        agent_docs = storage.docs["crew_agent_results"]
        eid = result.metadata["execution_id"]
        assert len(agent_docs) == 2  # one per iteration
        assert all(d["execution_id"] == eid for d in agent_docs)

    @pytest.mark.asyncio
    async def test_consolidated_doc_written(self):
        storage = _FakeStorage()
        crew = AgentCrew(
            name="c", agents=[_DummyAgent("a1", "ok")], auto_configure=False,
            result_storage=storage,
        )
        crew.workflow_graph = {}
        await crew.run_loop("start", condition="", max_iterations=1, generate_summary=False)
        await crew.aclose()

        assert len(storage.docs["crew_executions"]) == 1


class TestRunParallelWiring:
    @pytest.mark.asyncio
    async def test_persists_one_doc_per_agent(self):
        storage = _FakeStorage()
        crew = AgentCrew(
            name="c", agents=_two_agents(), auto_configure=False,
            result_storage=storage,
        )
        result = await crew.run_parallel(
            tasks=[{"agent_id": "a1", "query": "q1"}, {"agent_id": "a2", "query": "q2"}],
            generate_summary=False,
        )
        await crew.aclose()

        agent_docs = storage.docs["crew_agent_results"]
        eid = result.metadata["execution_id"]
        assert len(agent_docs) == 2
        assert all(d["execution_id"] == eid for d in agent_docs)

    @pytest.mark.asyncio
    async def test_persist_agent_results_false(self):
        storage = _FakeStorage()
        crew = AgentCrew(
            name="c", agents=_two_agents(), auto_configure=False,
            result_storage=storage, persist_agent_results=False,
        )
        await crew.run_parallel(
            tasks=[{"agent_id": "a1", "query": "q1"}, {"agent_id": "a2", "query": "q2"}],
            generate_summary=False,
        )
        await crew.aclose()

        assert storage.docs["crew_agent_results"] == []
        assert len(storage.docs["crew_executions"]) == 1


class TestRunFlowWiring:
    @pytest.mark.asyncio
    async def test_persists_one_doc_per_agent(self):
        storage = _FakeStorage()
        a1 = _DummyAgent("a1", "first")
        a2 = _DummyAgent("a2", "second")
        crew = AgentCrew(
            name="c", agents=[a1, a2], auto_configure=False, result_storage=storage,
        )
        crew.task_flow(a1, a2)
        result = await crew.run_flow("start", generate_summary=False)
        await crew.aclose()

        agent_docs = storage.docs["crew_agent_results"]
        eid = result.metadata["execution_id"]
        assert len(agent_docs) == 2
        assert all(d["execution_id"] == eid for d in agent_docs)
        assert {d["node_id"] for d in agent_docs} == {"a1", "a2"}

    @pytest.mark.asyncio
    async def test_consolidated_doc_written_with_agent_results(self):
        storage = _FakeStorage()
        a1 = _DummyAgent("a1", "first")
        a2 = _DummyAgent("a2", "second")
        crew = AgentCrew(
            name="c", agents=[a1, a2], auto_configure=False, result_storage=storage,
        )
        crew.task_flow(a1, a2)
        await crew.run_flow("start", generate_summary=False)
        await crew.aclose()

        crew_docs = storage.docs["crew_executions"]
        assert len(crew_docs) == 1
        assert len(crew_docs[0]["result"]["agent_results"]) == 2


class TestAcloseDrainsAgentTasks:
    @pytest.mark.asyncio
    async def test_aclose_drains_pending_agent_persist_tasks(self):
        storage = _FakeStorage()
        crew = AgentCrew(
            name="c", agents=_two_agents(), auto_configure=False,
            result_storage=storage,
        )
        await crew.run_sequential("task", generate_summary=False)
        # Some agent-persist tasks may still be in-flight at this point;
        # aclose() must await all of them (existing _persist_tasks contract).
        await crew.aclose()
        assert crew._persist_tasks == set()
