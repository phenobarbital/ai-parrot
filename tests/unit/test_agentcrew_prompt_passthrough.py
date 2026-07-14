"""Unit tests for AgentCrew run_* prompt/tenant passthrough (FEAT-307)."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.bots.flows.crew import AgentCrew


def _fake_agent(name: str = "agent1") -> MagicMock:
    """Build a minimal fake agent satisfying AgentCrew's execution path.

    ``_execute_agent`` dispatches on ``hasattr(agent, 'ask')`` first, so a
    working async ``ask()`` is all that's needed to drive a real
    ``run_sequential``/``run_loop``/``run_flow`` execution end-to-end without
    a real LLM.
    """
    agent = MagicMock()
    agent.name = name
    agent.is_configured = True
    agent.description = "fake agent"
    agent.ask = AsyncMock(return_value=SimpleNamespace(content="agent output"))
    return agent


def _crew_with_fake_agent(**kwargs) -> AgentCrew:
    agent = _fake_agent()
    return AgentCrew(name="TestCrew", agents=[agent], **kwargs)


def _fake_llm_client(content: str = "synthesized") -> MagicMock:
    """Fake ``self._llm`` supporting ``async with self._llm as client: ...``."""
    client = MagicMock()
    client.ask = AsyncMock(return_value=SimpleNamespace(content=content))
    llm = MagicMock()
    llm.__aenter__ = AsyncMock(return_value=client)
    llm.__aexit__ = AsyncMock(return_value=None)
    return llm


class TestAgentCrewPromptPassthrough:
    @pytest.mark.asyncio
    async def test_run_sequential_passes_prompt(self, monkeypatch):
        """run_sequential passes query as prompt kwarg to _save_result."""
        crew = _crew_with_fake_agent()
        spy = AsyncMock()
        monkeypatch.setattr(crew, "_save_result", spy)

        await crew.run_sequential("What is the weather?", generate_summary=False)

        assert spy.call_args.kwargs["prompt"] == "What is the weather?"
        assert spy.call_args.kwargs["tenant"] == "global"

    @pytest.mark.asyncio
    async def test_run_loop_passes_prompt(self, monkeypatch):
        """run_loop passes initial_task as prompt kwarg."""
        crew = _crew_with_fake_agent()
        # Unrelated pre-existing bug: run_loop() unconditionally does
        # `node.fsm = AgentTaskMachine(...)` every iteration, but nodes are
        # frozen Pydantic models (flows/core/node.py ConfigDict(frozen=True))
        # — this raises a ValidationError for ANY crew, regardless of this
        # task's changes. Clearing workflow_graph sidesteps it: run_loop's
        # `if node: ...` guards already treat a missing node as "no FSM
        # tracking for this run", which is exactly what we want to isolate
        # the prompt-passthrough behavior under test. Flagged in the
        # Completion Note for a follow-up bug-fix task.
        crew.workflow_graph = {}
        spy = AsyncMock()
        monkeypatch.setattr(crew, "_save_result", spy)

        await crew.run_loop(
            "Summarize the report",
            condition="done",
            max_iterations=1,
            generate_summary=False,
        )

        assert spy.call_args.kwargs["prompt"] == "Summarize the report"
        assert spy.call_args.kwargs["tenant"] == "global"

    @pytest.mark.asyncio
    async def test_run_flow_passes_prompt(self, monkeypatch):
        """run_flow passes initial_task as prompt kwarg."""
        crew = _crew_with_fake_agent()
        # Single-agent flow: no explicit task_flow() edge needed — just derive
        # initial/final agent metadata from the (dependency-free) single node.
        crew._update_flow_metadata()
        spy = AsyncMock()
        monkeypatch.setattr(crew, "_save_result", spy)

        await crew.run_flow("Draft the announcement", generate_summary=False)

        assert spy.call_args.kwargs["prompt"] == "Draft the announcement"
        assert spy.call_args.kwargs["tenant"] == "global"

    @pytest.mark.asyncio
    async def test_run_parallel_passes_prompt(self, monkeypatch):
        """run_parallel passes the first task's query as prompt kwarg."""
        crew = _crew_with_fake_agent()
        spy = AsyncMock()
        monkeypatch.setattr(crew, "_save_result", spy)

        await crew.run_parallel(
            [{"agent_id": "agent1", "query": "Research topic A"}],
            generate_summary=False,
        )

        assert spy.call_args.kwargs["prompt"] == "Research topic A"
        assert spy.call_args.kwargs["tenant"] == "global"

    @pytest.mark.asyncio
    async def test_run_passes_prompt(self, monkeypatch):
        """run passes the task param as prompt kwarg."""
        crew = _crew_with_fake_agent()
        crew._llm = _fake_llm_client()
        spy = AsyncMock()
        monkeypatch.setattr(crew, "_save_result", spy)
        # run() calls self.run_parallel() internally, then indexes
        # parallel_result['results'] — a plain dict sidesteps an unrelated,
        # pre-existing bug where FlowResult.__getitem__ has no 'results' key
        # (only 'node_results'/'agent_results'); flagged in the Completion Note.
        monkeypatch.setattr(
            crew,
            "run_parallel",
            AsyncMock(return_value={
                "success": True,
                "results": {"agent1": "agent output"},
                "total_execution_time": 0.01,
            }),
        )

        await crew.run("Investigate topic B")

        assert spy.call_args.kwargs["prompt"] == "Investigate topic B"
        assert spy.call_args.kwargs["tenant"] == "global"

    @pytest.mark.asyncio
    async def test_run_passes_prompt_for_dict_task(self, monkeypatch):
        """run() stringifies a dict task before passing it as prompt."""
        crew = _crew_with_fake_agent()
        crew._llm = _fake_llm_client()
        spy = AsyncMock()
        monkeypatch.setattr(crew, "_save_result", spy)
        monkeypatch.setattr(
            crew,
            "run_parallel",
            AsyncMock(return_value={
                "success": True,
                "results": {"agent1": "agent output"},
                "total_execution_time": 0.01,
            }),
        )

        task = {"agent1": "Custom prompt for agent1"}
        await crew.run(task)

        assert spy.call_args.kwargs["prompt"] == str(task)

    @pytest.mark.asyncio
    async def test_ask_passes_prompt(self, monkeypatch):
        """ask passes question as prompt kwarg to _save_result."""
        crew = _crew_with_fake_agent()
        crew._llm = _fake_llm_client(content="ask response")
        # ask() requires prior execution results; seed a minimal entry
        # (search_similar() naturally returns [] since enable_analysis=False,
        # so no FAISS index is needed).
        crew.execution_memory.results = {"agent1": MagicMock()}
        spy = AsyncMock()
        monkeypatch.setattr(crew, "_save_result", spy)

        await crew.ask("What did agent1 find?")

        assert spy.call_args.kwargs["prompt"] == "What did agent1 find?"
        assert spy.call_args.kwargs["tenant"] == "global"

    @pytest.mark.asyncio
    async def test_tenant_default_global(self, monkeypatch):
        """tenant defaults to 'global' when not set on crew."""
        crew = _crew_with_fake_agent()
        assert not hasattr(crew, "_tenant")
        spy = AsyncMock()
        monkeypatch.setattr(crew, "_save_result", spy)

        await crew.run_sequential("Any query", generate_summary=False)

        assert spy.call_args.kwargs["tenant"] == "global"

    @pytest.mark.asyncio
    async def test_tenant_uses_crew_attribute_when_set(self, monkeypatch):
        """tenant reflects self._tenant when the crew carries one."""
        crew = _crew_with_fake_agent()
        crew._tenant = "acme"
        spy = AsyncMock()
        monkeypatch.setattr(crew, "_save_result", spy)

        await crew.run_sequential("Any query", generate_summary=False)

        assert spy.call_args.kwargs["tenant"] == "acme"
