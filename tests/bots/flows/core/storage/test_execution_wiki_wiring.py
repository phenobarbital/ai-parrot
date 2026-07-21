"""AgentCrew wiring tests for the execution wiki.

Verifies that crew runs record the run, per-agent intermediate results,
and intermediate tool-call results into the per-crew WikiStore SQLite
plane; that the persisted ``crew_agent_results`` documents now carry the
serialised tool calls; and that the search surfaces (``search_execution``,
``ResultRetrievalTool.search_research``, the ``ask()`` prompt section)
are wired.

Uses the same local stub-agent + fake-storage pattern as
``test_crew_agent_persistence.py`` (FEAT-306), extended with tool-call
records on the stub responses.
"""
from __future__ import annotations

import types
from collections import defaultdict
from typing import Any, Dict, List, Optional

import pytest

from parrot.bots.flows.core.storage.backends import ResultStorage
from parrot.bots.flows.crew.crew import AgentCrew
from parrot.models.basic import ToolCall


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
    """Deterministic agent stub whose responses carry tool-call records."""

    is_configured: bool = True
    EVENT_STATUS_CHANGED: str = "status_changed"
    EVENT_TASK_STARTED: str = "task_started"
    EVENT_TASK_COMPLETED: str = "task_completed"
    EVENT_TASK_FAILED: str = "task_failed"

    def __init__(
        self,
        name: str,
        response: str = "ok",
        tool_calls: Optional[List[ToolCall]] = None,
    ) -> None:
        self._name = name
        self._response = response
        self._tool_calls = tool_calls or []
        self.tool_manager = _DummyToolManager()
        self.description = f"Agent {name}"

    @property
    def name(self) -> str:
        return self._name

    async def invoke(self, prompt: str, **kwargs: Any) -> Any:
        return await self.ask(question=prompt, **kwargs)

    async def ask(
        self, prompt: str = "", *, question: str = "", **kwargs: Any
    ) -> types.SimpleNamespace:
        effective_prompt = question or prompt
        return types.SimpleNamespace(
            content=f"{self._response}: {effective_prompt[:40]}",
            tool_calls=list(self._tool_calls),
        )

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


def _searcher_tool_call() -> ToolCall:
    return ToolCall(
        id="tc-1",
        name="web_search",
        arguments={"query": "quokka population"},
        result="the quokka census counted 14000 individuals",
        execution_time=0.7,
    )


def _crew(tmp_path, **kwargs) -> AgentCrew:
    agents = kwargs.pop("agents", None) or [
        _DummyAgent("a1", "first", tool_calls=[_searcher_tool_call()]),
        _DummyAgent("a2", "second"),
    ]
    return AgentCrew(
        name="wikicrew",
        agents=agents,
        auto_configure=False,
        result_storage=kwargs.pop("result_storage", _FakeStorage()),
        execution_wiki_path=tmp_path / "crew_wiki",
        **kwargs,
    )


class TestSequentialRecording:
    @pytest.mark.asyncio
    async def test_run_records_pages_and_tool_calls(self, tmp_path):
        crew = _crew(tmp_path)
        result = await crew.run_sequential("task", generate_summary=False)
        wiki = crew.execution_wiki
        await crew.aclose()

        eid = result.metadata["execution_id"]
        run_page = await wiki.get_page(f"run:{eid}")
        assert run_page is not None
        assert "run_sequential" in run_page["body"]
        # Final output appended by record_run_end
        assert "Final Output" in run_page["body"]

        agent_page = await wiki.get_page(f"agent:{eid}:a1")
        assert agent_page is not None
        assert agent_page["category"] == "agent_result"

        tool_page = await wiki.get_page(f"tool:{eid}:a1:tc-1")
        assert tool_page is not None
        assert "quokka census" in tool_page["body"]

    @pytest.mark.asyncio
    async def test_search_execution_finds_tool_result(self, tmp_path):
        crew = _crew(tmp_path)
        await crew.run_sequential("task", generate_summary=False)
        await crew.aclose()

        hits = await crew.search_execution("quokka census")
        assert hits
        assert hits[0]["category"] == "tool_result"

    @pytest.mark.asyncio
    async def test_agent_docs_carry_tool_calls(self, tmp_path):
        storage = _FakeStorage()
        crew = _crew(tmp_path, result_storage=storage)
        await crew.run_sequential("task", generate_summary=False)
        await crew.aclose()

        docs = {d["node_id"]: d for d in storage.docs["crew_agent_results"]}
        a1_calls = docs["a1"]["tool_calls"]
        assert len(a1_calls) == 1
        assert a1_calls[0]["name"] == "web_search"
        assert "quokka census" in a1_calls[0]["result"]
        assert docs["a2"]["tool_calls"] == []


class TestOtherModesRecording:
    @pytest.mark.asyncio
    async def test_parallel_records_agent_and_tool_pages(self, tmp_path):
        crew = _crew(tmp_path)
        result = await crew.run_parallel(
            tasks=[
                {"agent_id": "a1", "query": "q1"},
                {"agent_id": "a2", "query": "q2"},
            ],
            generate_summary=False,
        )
        wiki = crew.execution_wiki
        await crew.aclose()

        eid = result.metadata["execution_id"]
        assert await wiki.get_page(f"run:{eid}") is not None
        assert await wiki.get_page(f"agent:{eid}:a1") is not None
        assert await wiki.get_page(f"tool:{eid}:a1:tc-1") is not None

    @pytest.mark.asyncio
    async def test_flow_records_agent_and_tool_pages(self, tmp_path):
        a1 = _DummyAgent("a1", "first", tool_calls=[_searcher_tool_call()])
        a2 = _DummyAgent("a2", "second")
        crew = _crew(tmp_path, agents=[a1, a2])
        crew.task_flow(a1, a2)
        result = await crew.run_flow("start", generate_summary=False)
        wiki = crew.execution_wiki
        await crew.aclose()

        eid = result.metadata["execution_id"]
        assert await wiki.get_page(f"run:{eid}") is not None
        assert await wiki.get_page(f"agent:{eid}:a1") is not None
        assert await wiki.get_page(f"tool:{eid}:a1:tc-1") is not None

    @pytest.mark.asyncio
    async def test_loop_records_iteration_pages(self, tmp_path):
        crew = _crew(
            tmp_path,
            agents=[_DummyAgent("a1", "ok", tool_calls=[_searcher_tool_call()])],
        )
        # Sidestep the pre-existing frozen-FSM reassignment bug in run_loop
        # (see test_crew_agent_persistence.py::TestRunLoopWiring).
        crew.workflow_graph = {}
        result = await crew.run_loop(
            "start", condition="", max_iterations=1, generate_summary=False,
        )
        wiki = crew.execution_wiki
        await crew.aclose()

        eid = result.metadata["execution_id"]
        assert await wiki.get_page(f"run:{eid}") is not None
        # Loop node ids are "<agent>#iteration<n>"
        assert await wiki.get_page(f"agent:{eid}:a1#iteration1") is not None


class TestGating:
    @pytest.mark.asyncio
    async def test_enable_execution_wiki_false_writes_nothing(self, tmp_path):
        crew = _crew(tmp_path, enable_execution_wiki=False)
        await crew.run_sequential("task", generate_summary=False)
        await crew.aclose()

        assert not (tmp_path / "crew_wiki").exists()
        assert await crew.search_execution("anything") == []

    @pytest.mark.asyncio
    async def test_persist_results_false_writes_nothing(self, tmp_path):
        crew = _crew(tmp_path, persist_results=False)
        await crew.run_sequential("task", generate_summary=False)
        await crew.aclose()

        assert not (tmp_path / "crew_wiki").exists()

    @pytest.mark.asyncio
    async def test_aclose_clears_recorder(self, tmp_path):
        crew = _crew(tmp_path)
        await crew.run_sequential("task", generate_summary=False)
        assert crew._execution_wiki is not None
        await crew.aclose()
        assert crew._execution_wiki is None


class TestSearchSurfaces:
    @pytest.mark.asyncio
    async def test_retrieval_tool_search_research_and_read_page(self, tmp_path):
        crew = _crew(tmp_path)
        result = await crew.run_sequential("task", generate_summary=False)
        await crew.aclose()

        out = await crew.retrieval_tool._execute(
            action="search_research", query="quokka census"
        )
        assert "tool_result" in out
        eid = result.metadata["execution_id"]
        assert f"tool:{eid}:a1:tc-1" in out

        page_out = await crew.retrieval_tool._execute(
            action="read_research_page", page_id=f"tool:{eid}:a1:tc-1"
        )
        assert "quokka census counted 14000" in page_out

    @pytest.mark.asyncio
    async def test_retrieval_tool_degrades_when_wiki_disabled(self, tmp_path):
        crew = _crew(tmp_path, enable_execution_wiki=False)
        out = await crew.retrieval_tool._execute(
            action="search_research", query="anything"
        )
        assert "not available" in out

    @pytest.mark.asyncio
    async def test_ask_prompt_renders_research_section(self, tmp_path):
        crew = _crew(tmp_path)
        context = crew._build_ask_context(
            semantic_results=[],
            textual_context={},
            question="what about quokkas?",
            research_matches=[{
                "concept_id": "tool:e1:a1:tc-1",
                "title": "web_search — tool call by a1 (e1)",
                "category": "tool_result",
                "summary": "web_search({...})",
                "score": 0.91,
                "content": "the quokka census counted 14000 individuals",
            }],
        )
        prompt = crew._build_ask_user_prompt("what about quokkas?", context)
        assert "Research Wiki Matches" in prompt
        assert "tool:e1:a1:tc-1" in prompt
        assert "quokka census counted 14000" in prompt

    @pytest.mark.asyncio
    async def test_ask_prompt_without_research_matches_unchanged(self, tmp_path):
        crew = _crew(tmp_path, enable_execution_wiki=False)
        context = crew._build_ask_context(
            semantic_results=[], textual_context={}, question="q?",
        )
        prompt = crew._build_ask_user_prompt("q?", context)
        assert "Research Wiki Matches" not in prompt
