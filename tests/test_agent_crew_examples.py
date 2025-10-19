"""Integration-style tests for crew orchestration modes.

These tests provide lightweight smoke coverage for the sequential,
parallel, flow-based, and FSM orchestration helpers exposed by
``AgentCrew`` and ``AgentsFlow``.  Instead of relying on real LLM-backed
``BasicAgent`` instances (which would require network access and costly
initialisation) the suite drives the orchestrators with deterministic
stub agents that emulate the minimal behaviour required by the
orchestration layers.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from parrot.bots.orchestration.crew import AgentCrew
from parrot.bots.orchestration.fsm import AgentsFlow, TransitionCondition


class DummyToolManager:
    """Minimal stand-in for the real ToolManager used in tests."""

    def __init__(self) -> None:
        self._tools: Dict[str, Any] = {}

    def add_tool(self, tool: Any, tool_name: Optional[str] = None) -> None:
        name = tool_name or getattr(tool, "name", str(tool))
        self._tools[name] = tool

    def get_tool(self, tool_name: Optional[str]) -> Any:
        return self._tools.get(tool_name or "")

    def list_tools(self) -> List[str]:
        return list(self._tools.keys())


@dataclass
class DummyResponse:
    """Simple response object exposing a ``content`` attribute."""

    content: str


class DummyAgent:
    """Deterministic agent used to exercise orchestration logic."""

    def __init__(
        self,
        name: str,
        response: Callable[[str], str] | str,
    ) -> None:
        self.name = name
        self.tool_manager = DummyToolManager()
        self._response_builder: Callable[[str], str]
        if callable(response):
            self._response_builder = response  # type: ignore[assignment]
        else:
            self._response_builder = lambda prompt: response
        self.is_configured: bool = False
        self.configure_calls: int = 0
        self.ask_calls: int = 0
        self.received_prompts: List[str] = []

    async def configure(self) -> None:
        self.configure_calls += 1
        self.is_configured = True

    async def ask(self, question: str, **_: Any) -> DummyResponse:
        self.ask_calls += 1
        self.received_prompts.append(question)
        return DummyResponse(self._response_builder(question))


class DummyLoopLLM:
    """LLM stub that decides whether to stop the loop based on the prompt."""

    def __init__(self, decision_fn: Callable[[str], str]) -> None:
        self._decision_fn = decision_fn
        self.prompts: List[str] = []

    async def __aenter__(self) -> "DummyLoopLLM":
        return self

    async def __aexit__(self, *_: Any) -> bool:
        return False

    async def ask(self, prompt: str, **_: Any) -> DummyResponse:
        self.prompts.append(prompt)
        return DummyResponse(self._decision_fn(prompt))


def test_agentcrew_sequential_execution_passes_context() -> None:
    """Verify ``run_sequential`` pipelines agents and aggregates metadata."""

    researcher_output = "Research summary"
    analyzer_output = "Analyzer insights"
    reporter_output = "Reporter wrap-up"

    researcher = DummyAgent("Researcher", researcher_output)
    analyzer = DummyAgent("Analyzer", analyzer_output)
    reporter = DummyAgent("Reporter", reporter_output)

    crew = AgentCrew(
        name="TestSequentialCrew",
        agents=[researcher, analyzer, reporter],
        shared_tool_manager=DummyToolManager(),
    )

    result = asyncio.run(crew.run_sequential(query="Investigate widgets"))

    # Pipeline execution order and outputs are preserved
    assert result.status == "completed"
    assert result.output == reporter_output
    assert result.agent_ids == ["Researcher", "Analyzer", "Reporter"]
    assert result.agent_results == {
        "Researcher": researcher_output,
        "Analyzer": analyzer_output,
        "Reporter": reporter_output,
    }
    assert result.metadata["mode"] == "sequential"
    assert result.completed == ["Researcher", "Analyzer", "Reporter"]
    assert result.failed == []

    # Downstream agents receive upstream results in their prompt
    assert researcher.configure_calls == 1
    assert analyzer.configure_calls == 1
    assert reporter.configure_calls == 1
    assert researcher.received_prompts == ["Investigate widgets"]
    assert researcher_output in analyzer.received_prompts[0]
    assert analyzer_output in reporter.received_prompts[0]


def test_agentcrew_parallel_execution_returns_all_results() -> None:
    """Ensure ``run_parallel`` triggers all agents concurrently."""

    info_agent = DummyAgent("InfoAgent", "Specs located")
    price_agent = DummyAgent("PriceAgent", "Prices gathered")
    review_agent = DummyAgent("ReviewAgent", "Reviews summarised")

    crew = AgentCrew(
        name="TestParallelCrew",
        agents=[info_agent, price_agent, review_agent],
        shared_tool_manager=DummyToolManager(),
    )

    tasks = [
        {"agent_id": "InfoAgent", "query": "Find specs"},
        {"agent_id": "PriceAgent", "query": "Find prices"},
        {"agent_id": "ReviewAgent", "query": "Find reviews"},
    ]

    result = asyncio.run(crew.run_parallel(tasks))

    assert result.status == "completed"
    assert result.metadata["mode"] == "parallel"
    assert result.agent_results == {
        "InfoAgent": "Specs located",
        "PriceAgent": "Prices gathered",
        "ReviewAgent": "Reviews summarised",
    }
    assert set(result.agent_ids) == {"InfoAgent", "PriceAgent", "ReviewAgent"}
    assert info_agent.configure_calls == 1
    assert price_agent.configure_calls == 1
    assert review_agent.configure_calls == 1
    assert info_agent.received_prompts == ["Find specs"]
    assert price_agent.received_prompts == ["Find prices"]
    assert review_agent.received_prompts == ["Find reviews"]


def test_agentcrew_parallel_execution_all_results() -> None:
    """Ensure ``run_parallel`` triggers all agents concurrently."""

    info_agent = DummyAgent("InfoAgent", "Specs located")
    price_agent = DummyAgent("PriceAgent", "Prices gathered")
    review_agent = DummyAgent("ReviewAgent", "Reviews summarised")

    crew = AgentCrew(
        name="TestParallelCrew",
        agents=[info_agent, price_agent, review_agent],
        shared_tool_manager=DummyToolManager(),
    )

    tasks = [
        {"agent_id": "InfoAgent", "query": "Find specs"},
        {"agent_id": "PriceAgent", "query": "Find prices"},
        {"agent_id": "ReviewAgent", "query": "Find reviews"},
    ]

    result = asyncio.run(crew.run_parallel(tasks, all_results=True))

    assert result.status == "completed"
    assert result.metadata["mode"] == "parallel"
    assert result.output == [
        "Specs located",
        "Prices gathered",
        "Reviews summarised",
    ]
    assert set(result.agent_ids) == {"InfoAgent", "PriceAgent", "ReviewAgent"}
    assert info_agent.configure_calls == 1
    assert price_agent.configure_calls == 1
    assert review_agent.configure_calls == 1
    assert info_agent.received_prompts == ["Find specs"]
    assert price_agent.received_prompts == ["Find prices"]
    assert review_agent.received_prompts == ["Find reviews"]


def test_agentcrew_flow_execution_respects_dependencies() -> None:
    """``run_flow`` should fan-out/fan-in according to the DAG definition."""

    writer_output = "Initial draft"
    editor1_output = "Grammar fixed"
    editor2_output = "Style improved"
    reviewer_output = "Final copy"

    writer = DummyAgent("writer", writer_output)
    editor1 = DummyAgent("editor1", editor1_output)
    editor2 = DummyAgent("editor2", editor2_output)
    final_reviewer = DummyAgent("final_reviewer", reviewer_output)

    crew = AgentCrew(
        name="TestFlowCrew",
        agents=[writer, editor1, editor2, final_reviewer],
        shared_tool_manager=DummyToolManager(),
    )

    crew.task_flow(writer, [editor1, editor2])
    crew.task_flow(editor1, final_reviewer)
    crew.task_flow(editor2, final_reviewer)

    result = asyncio.run(crew.run_flow(initial_task="Write about climate change"))

    assert result.status == "completed"
    assert result.metadata["mode"] == "flow"
    assert result.output == reviewer_output
    assert set(result.agent_ids) == {"writer", "editor1", "editor2", "final_reviewer"}
    assert set(result.completed) == {"writer", "editor1", "editor2", "final_reviewer"}
    assert result.failed == []

    # Editors see writer output and final reviewer sees both editor outputs
    assert writer.received_prompts == ["Write about climate change"]
    assert writer_output in editor1.received_prompts[0]
    assert writer_output in editor2.received_prompts[0]
    assert editor1_output in final_reviewer.received_prompts[0]
    assert editor2_output in final_reviewer.received_prompts[0]


def test_agentcrew_loop_execution_stops_when_condition_met() -> None:
    """``run_loop`` should reuse outputs and stop when the LLM approves."""

    def sequential_responses(outputs: List[str]) -> Callable[[str], str]:
        call_index = {"value": 0}

        def builder(_: str) -> str:
            value = outputs[call_index["value"]]
            call_index["value"] += 1
            return value

        return builder

    researcher_outputs = ["Draft outline", "Refined outline"]
    reviewer_outputs = ["Needs revision", "FINAL report"]

    researcher = DummyAgent("Researcher", sequential_responses(researcher_outputs))
    reviewer = DummyAgent("Reviewer", sequential_responses(reviewer_outputs))

    loop_llm = DummyLoopLLM(
        lambda prompt: "YES" if "FINAL report" in prompt else "NO"
    )

    crew = AgentCrew(
        name="TestLoopCrew",
        agents=[researcher, reviewer],
        shared_tool_manager=DummyToolManager(),
        llm=loop_llm,
    )

    result = asyncio.run(
        crew.run_loop(
            initial_task="Create a market analysis",
            condition="Stop when the reviewer marks the report as FINAL",
            max_iterations=4,
        )
    )

    assert result.status == "completed"
    assert result.metadata["mode"] == "loop"
    assert result.metadata["condition_met"] is True
    assert result.metadata["iterations"] == 2
    assert result.output == "FINAL report"

    assert "Create a market analysis" in researcher.received_prompts[0]
    assert "Needs revision" in researcher.received_prompts[1]

    assert len(loop_llm.prompts) == 2

    shared_state = result.metadata["shared_state"]
    assert len(shared_state["history"]) == 4
    assert shared_state["iteration_outputs"][-1] == "FINAL report"


def test_agentsflow_fsm_execution_records_transitions() -> None:
    """Exercise the FSM-based ``AgentsFlow`` orchestration path."""

    researcher_output = "Trends collected"
    analyzer_output = "Insights extracted"
    writer_output = "Report drafted"
    fixer_output = "Issue resolved"

    researcher = DummyAgent("researcher", researcher_output)
    analyzer = DummyAgent("analyzer", analyzer_output)
    writer = DummyAgent("writer", writer_output)
    fixer = DummyAgent("error_handler", fixer_output)

    crew = AgentsFlow(
        name="TestFSMCrew",
        shared_tool_manager=DummyToolManager(),
    )

    researcher_node = crew.add_agent(researcher)
    analyzer_node = crew.add_agent(analyzer)
    writer_node = crew.add_agent(writer)
    fixer_node = crew.add_agent(fixer)

    crew.task_flow(researcher_node, analyzer_node)
    crew.task_flow(analyzer_node, writer_node)
    crew.task_flow(
        analyzer_node,
        fixer_node,
        condition=TransitionCondition.ON_ERROR,
        instruction="Fix the issue and retry",
    )
    crew.task_flow(fixer_node, analyzer_node)

    result = asyncio.run(crew.run_flow(initial_task="Research AI trends"))

    assert result.status == "completed"
    assert result.metadata["mode"] == "fsm"
    assert result.output == writer_output
    assert set(result.completed) >= {"researcher", "analyzer", "writer"}
    assert "error_handler" not in result.completed
    assert result.failed == []

    assert researcher.configure_calls == 1
    assert analyzer.configure_calls == 1
    assert writer.configure_calls == 1
    assert fixer.configure_calls == 0

    assert researcher.received_prompts == ["Research AI trends"]
    assert researcher_output in analyzer.received_prompts[0]
    assert analyzer_output in writer.received_prompts[0]
