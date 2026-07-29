"""
Regression tests for `AgentCrew.run_loop()`'s FSM reset (FEAT-309).

TASK-1782: Regression Tests for run_loop() FSM Reset

Verifies TASK-1781's one-line fix (`object.__setattr__(node, "fsm", ...)`
replacing the direct `node.fsm = ...` frozen-Pydantic reassignment): the
loop completes without `pydantic_core.ValidationError` across 0/1/many
agents and multiple iterations, and each iteration's FSM is genuinely
fresh (a new object instance, not a mutated leftover from a prior
iteration).

NOTE (Codebase Contract correction): the task's own Codebase Contract
suggested reusing `DummyAgent`/`fake_llm` from `tests/integration/conftest.py`
via `from tests.integration.conftest import DummyAgent`. Verified this does
NOT work: the top-level `tests/` directory has no `__init__.py` (confirmed
via `test -f tests/__init__.py`), so `tests` is not a regular importable
package and `tests.integration.conftest` cannot be imported from
`tests/unit/`. Pytest fixtures are also scoped by conftest.py directory
hierarchy, not by import, so `tests/integration/conftest.py`'s fixtures are
not visible here either. Falls back to an inline `DummyAgent`/`fake_llm`
(mirroring the exact shape already used in
`tests/integration/conftest.py` and `packages/ai-parrot/tests/_crew_test_helpers.py`),
per the task's own documented fallback guidance.
"""
from __future__ import annotations

import types
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.bots.flows.crew.crew import AgentCrew
from parrot.clients.base import AbstractClient


class _DummyToolManager:
    """Minimal ToolManager stand-in compatible with ``AgentCrew.add_agent()``."""

    def __init__(self) -> None:
        self._tools: Dict[str, Any] = {}

    def add_tool(self, tool: Any, tool_name: str = None) -> None:
        name = tool_name or getattr(tool, "name", str(tool))
        self._tools[name] = tool

    def get_tool(self, tool_name: str) -> Any:
        return self._tools.get(tool_name or "")

    def list_tools(self) -> List[str]:
        return list(self._tools.keys())


class DummyAgent:
    """Deterministic stub agent compatible with ``AgentCrew.add_agent()``/``run_*()``."""

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
    def name(self) -> str:  # noqa: D401
        return self._name

    async def invoke(self, prompt: str, **kwargs: Any) -> Any:
        return await self.ask(question=prompt, **kwargs)

    async def ask(self, prompt: str = "", *, question: str = "", **kwargs: Any):
        effective_prompt = question or prompt
        self.prompts_received.append(effective_prompt)
        return types.SimpleNamespace(content=f"{self._response}: {effective_prompt[:40]}")

    def add_event_listener(self, event: str, handler: Any) -> None:
        """No-op for tests."""

    def as_tool(self, **kwargs: Any) -> None:
        return None

    async def configure(self) -> None:
        """No-op configure."""


@pytest.fixture
def fake_llm() -> MagicMock:
    """Deterministic AbstractClient stub — never satisfies the loop condition.

    ``_evaluate_loop_condition()`` extracts text from ``client.ask()``'s
    response and only stops the loop when it starts with "yes" or contains
    " stop"; this canned response never does, so ``run_loop()`` always runs
    the full ``max_iterations`` deterministically (crew.py:1231-1238).
    """
    llm = MagicMock(spec=AbstractClient)
    llm.__aenter__ = AsyncMock(return_value=llm)
    llm.__aexit__ = AsyncMock(return_value=False)
    llm.ask = AsyncMock(
        return_value=types.SimpleNamespace(content="Continuing, condition not yet met.")
    )
    llm.register_tool = MagicMock()
    return llm


class TestRunLoopNoValidationError:
    @pytest.mark.asyncio
    async def test_run_loop_single_agent_single_iteration(self, fake_llm):
        """1 agent, max_iterations=1 -> completes without ValidationError."""
        agent = DummyAgent("researcher", response="ok")
        crew = AgentCrew(name="test-crew", agents=[agent], llm=fake_llm, auto_configure=False)
        result = await crew.run_loop(
            "start", condition="never true", max_iterations=1, generate_summary=False,
        )
        assert result is not None
        assert result.status in ("completed", "partial", "failed")

    @pytest.mark.asyncio
    async def test_run_loop_multiple_agents_multiple_iterations(self, fake_llm):
        """3 agents, max_iterations=3 -> all iterations complete without error."""
        agents = [DummyAgent(f"agent-{i}", response=f"ok-{i}") for i in range(3)]
        crew = AgentCrew(name="test-crew", agents=agents, llm=fake_llm, auto_configure=False)
        result = await crew.run_loop(
            "start", condition="never true", max_iterations=3, generate_summary=False,
        )
        assert result is not None
        assert result.metadata.get("iterations") == 3

    @pytest.mark.asyncio
    async def test_run_loop_zero_agents_no_validation_error(self, fake_llm):
        """0 agents -> graceful failure result, no ValidationError raised."""
        crew = AgentCrew(name="test-crew", agents=[], llm=fake_llm, auto_configure=False)
        result = await crew.run_loop(
            "start", condition="never true", max_iterations=1, generate_summary=False,
        )
        assert result is not None
        assert result.status == "failed"


class TestRunLoopFsmIsFreshEachIteration:
    @pytest.mark.asyncio
    async def test_fsm_object_identity_changes_across_iterations(self, fake_llm):
        """After the run, the node's fsm is a fresh object (not the pre-run instance)."""
        agent = DummyAgent("researcher", response="ok")
        crew = AgentCrew(name="test-crew", agents=[agent], llm=fake_llm, auto_configure=False)
        node = crew.workflow_graph["researcher"]
        fsm_before = node.fsm

        await crew.run_loop(
            "start", condition="never true", max_iterations=2, generate_summary=False,
        )

        node_after = crew.workflow_graph["researcher"]
        assert node_after.fsm is not fsm_before

    @pytest.mark.asyncio
    async def test_fsm_reaches_terminal_state_each_iteration(self, fake_llm):
        """Each iteration's FSM reaches completed/failed (a final/terminal state)."""
        agent = DummyAgent("researcher", response="ok")
        crew = AgentCrew(name="test-crew", agents=[agent], llm=fake_llm, auto_configure=False)

        await crew.run_loop(
            "start", condition="never true", max_iterations=1, generate_summary=False,
        )

        node = crew.workflow_graph["researcher"]
        assert str(node.fsm.current_state.id) in ("completed", "failed")


class TestOtherModesUnaffected:
    @pytest.mark.asyncio
    async def test_run_flow_sequential_parallel_unaffected(self, fake_llm):
        """Smoke-level regression guard: the other 3 modes still work.

        None of run_flow/run_sequential/run_parallel touch the per-iteration
        FSM-reset code path this fix changes (verified via grep: exactly one
        `node.fsm = ...`-style call site exists in the whole
        parrot/bots/flows/ tree, inside run_loop()). This is a smoke check,
        not a full regression suite — the dedicated regression suites
        (test_crew_flow_regression.py, test_crew_sequential_regression.py,
        test_crew_parallel_regression.py in packages/ai-parrot/tests/) remain
        the source of truth and must also be re-run as part of this task's
        acceptance criteria.
        """
        agents = [DummyAgent(f"agent-{i}", response=f"ok-{i}") for i in range(2)]

        crew_seq = AgentCrew(name="seq-crew", agents=agents, llm=fake_llm, auto_configure=False)
        result_seq = await crew_seq.run_sequential("start", generate_summary=False)
        assert result_seq.status == "completed"

        crew_par = AgentCrew(name="par-crew", agents=agents, llm=fake_llm, auto_configure=False)
        result_par = await crew_par.run_parallel(
            tasks=[{"agent_id": a.name, "query": "start"} for a in agents],
            generate_summary=False,
        )
        assert result_par is not None

        crew_flow = AgentCrew(name="flow-crew", agents=agents, llm=fake_llm, auto_configure=False)
        crew_flow.task_flow(agents[0], agents[1])
        result_flow = await crew_flow.run_flow("start", generate_summary=False)
        assert result_flow.status == "completed"
