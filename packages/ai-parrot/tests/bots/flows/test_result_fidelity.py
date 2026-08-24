"""Crew/flow FlowResult parity contract — FEAT-447 TASK-2330.

`AgentCrew` and `AgentsFlow` return the *same* public contract
(`FlowResult`), and before FEAT-447 only the crew populated it faithfully:
AgentsFlow lost every node's `usage`/`tool_calls` and left `total_time`,
`execution_log` and `metadata` at their dataclass defaults.

This module is the regression guard that keeps the two executors from
drifting apart again (spec G5). It drives the *same* agent stubs through both
executors and asserts that the same `FlowResult` fields — and the same
`NodeExecutionInfo` fields — come back populated, with exactly one documented
exemption.

It deliberately asserts **populated-ness, not equality of values**: the two
executors orchestrate differently, so node ids, timings and log contents
legitimately differ.

Regression command (the AC-level check, run manually rather than shelled out
to from a test — a test that invokes pytest would recurse):

    pytest packages/ai-parrot/tests/bots/flows/ \\
           packages/ai-parrot/tests/test_flow_primitives/ \\
           packages/ai-parrot/tests/flows/checkpoint/ \\
           packages/ai-parrot/tests/test_crew_sequential_regression.py \\
           packages/ai-parrot/tests/test_crew_parallel_regression.py \\
           packages/ai-parrot/tests/test_crew_final_regression.py -v
"""
from __future__ import annotations

import dataclasses
from typing import Any

from parrot.bots.flows.core.node import AgentNode
from parrot.bots.flows.core.result import FlowResult, NodeExecutionInfo
from parrot.bots.flows.crew import AgentCrew
from parrot.bots.flows.flow import AgentsFlow

# ---------------------------------------------------------------------------
# The exemption list — widening this must be a deliberate, reviewed edit.
# ---------------------------------------------------------------------------

PARITY_EXEMPT_FIELDS = frozenset({
    # `summary` is the ONE legitimate divergence. AgentCrew mixes in
    # SynthesisMixin and can synthesise a summary; AgentsFlow deliberately
    # inherits only PersistenceMixin (flow/flow.py class declaration and its
    # module docstring say so explicitly), leaving synthesis opt-in through
    # the standalone `synthesize_results` util. An empty `summary` on a flow
    # run is therefore a DESIGN DECISION (FEAT-447 Non-Goals / AC12), not a
    # fidelity loss. Do not "fix" it by adding SynthesisMixin to AgentsFlow.
    "summary",
})

#: `NodeExecutionInfo` fields both executors must populate for a successful
#: LLM-backed node. `error` is excluded (it is `None` on success by design)
#: and so are `node_id`/`node_name` (always set, and their *values* differ
#: between executors by construction).
NODE_PARITY_FIELDS = (
    "model",
    "provider",
    "usage",
    "tool_calls",
    "client",
    "execution_time",
    "status",
)


# ---------------------------------------------------------------------------
# Shared agent stub — driven through BOTH executors
# ---------------------------------------------------------------------------


class ParityAgent:
    """Agent stub returning a REAL `AgentResponse` carrying usage + tool calls.

    Deliberately usable by both executors without adaptation:

    * `AgentCrew._execute_agent` calls
      ``ask(question=..., session_id=..., user_id=..., model=...,
      max_tokens=..., use_conversation_history=...)``;
    * `AgentNode.execute` calls ``ask(question=..., _trusted_source=True)``.

    A real `CompletionUsage` is mandatory — `build_node_metadata` calls
    ``usage.model_dump()``, so a `MagicMock` would make every downstream
    assertion vacuous.
    """

    # AgentCrew lazily configures agents unless they report ready, and
    # registers listeners against these event-name constants (same surface
    # the shared `DummyAgent` in tests/_crew_test_helpers.py exposes).
    is_configured: bool = True
    EVENT_STATUS_CHANGED: str = "status_changed"
    EVENT_TASK_STARTED: str = "task_started"
    EVENT_TASK_COMPLETED: str = "task_completed"
    EVENT_TASK_FAILED: str = "task_failed"

    def __init__(self, name: str, reply: str = "ok", delay: float = 0.0) -> None:
        self._name = name
        self.reply = reply
        self.delay = delay
        self.description = f"Parity agent {name}"
        self.prompts_received: list[str] = []
        # `build_node_metadata` derives NodeExecutionInfo.client from the
        # concrete class of `agent.llm` (spec AC3).
        self.llm = type("FakeOpenAIClient", (), {"model": "gpt-4o"})()

    @property
    def name(self) -> str:
        return self._name

    async def configure(self) -> None:
        """No-op — the stub is always ready."""

    def add_event_listener(self, event: str, handler: Any) -> None:
        """No-op; AgentCrew registers listeners on its members."""

    async def invoke(self, prompt: str = "", **kwargs: Any) -> Any:
        """AgentLike protocol method — delegates to `ask`."""
        return await self.ask(question=prompt, **kwargs)

    async def ask(
        self, prompt: str = "", *, question: str = "", **kwargs: Any
    ) -> Any:
        import asyncio

        from parrot.models.basic import CompletionUsage, ToolCall
        from parrot.models.responses import AgentResponse, AIMessage

        effective = question or prompt
        self.prompts_received.append(effective)
        if self.delay:
            await asyncio.sleep(self.delay)

        message = AIMessage(
            input=effective,
            output=self.reply,
            model="gpt-4o",
            provider="openai",
            usage=CompletionUsage(
                prompt_tokens=13, completion_tokens=5, total_tokens=18
            ),
            tool_calls=[
                ToolCall(id="tc-1", name="search", arguments={"q": effective})
            ],
        )
        return AgentResponse(
            agent_id=self._name, agent_name=self._name, question=effective,
            response=message, output=self.reply,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _populated_fields(result: FlowResult) -> set[str]:
    """Field names whose value differs from the dataclass default.

    Args:
        result: The `FlowResult` to inspect.

    Returns:
        Set of field names carrying a non-default value. Fields with no
        declared default (i.e. `output`) count as populated when truthy.
    """
    populated: set[str] = set()
    for field in dataclasses.fields(result):
        value = getattr(result, field.name)
        if field.default is not dataclasses.MISSING:
            default: Any = field.default
        elif field.default_factory is not dataclasses.MISSING:  # type: ignore[misc]
            default = field.default_factory()  # type: ignore[misc]
        else:
            # No default declared (`output`): treat any truthy value as set.
            if value:
                populated.add(field.name)
            continue
        if value != default:
            populated.add(field.name)
    return populated


def _describe_divergence(
    crew_fields: set[str], flow_fields: set[str]
) -> str:
    """Render a directional, self-explaining parity failure message."""
    crew_only = sorted((crew_fields - flow_fields) - PARITY_EXEMPT_FIELDS)
    flow_only = sorted((flow_fields - crew_fields) - PARITY_EXEMPT_FIELDS)
    lines = [
        "FlowResult field parity broken between AgentCrew and AgentsFlow.",
        f"  crew populated: {sorted(crew_fields)}",
        f"  flow populated: {sorted(flow_fields)}",
    ]
    if crew_only:
        lines.append(
            f"  ONLY the crew populates {crew_only} — AgentsFlow regressed "
            "(see FEAT-447 TASK-2328/2329: _aggregate_result / run_flow wiring)."
        )
    if flow_only:
        lines.append(
            f"  ONLY the flow populates {flow_only} — the crew regressed, or a "
            "new field needs a documented exemption."
        )
    lines.append(
        f"  exempt (not compared): {sorted(PARITY_EXEMPT_FIELDS)}"
    )
    return "\n".join(lines)


def _unpopulated_node_fields(info: NodeExecutionInfo) -> list[str]:
    """Names of `NODE_PARITY_FIELDS` left empty/None on a successful node."""
    missing = []
    for name in NODE_PARITY_FIELDS:
        value = getattr(info, name)
        if value is None or value == [] or value == {} or value == 0.0:
            missing.append(name)
    return missing


async def _run_crew() -> FlowResult:
    """Drive two ParityAgents through AgentCrew.run_sequential()."""
    crew = AgentCrew(
        name="ParityCrew",
        agents=[
            ParityAgent("a1", reply="out_a", delay=0.015),
            ParityAgent("a2", reply="out_b", delay=0.015),
        ],
        auto_configure=False,
    )
    return await crew.run_sequential("start", generate_summary=False)


async def _run_flow() -> FlowResult:
    """Drive two ParityAgents through AgentsFlow.run_flow()."""
    flow = AgentsFlow("parity-flow")
    flow.add_node(
        AgentNode(
            agent=ParityAgent("a1", reply="out_a", delay=0.015),
            node_id="a1", dependencies=set(), successors={"a2"},
        )
    )
    flow.add_node(
        AgentNode(
            agent=ParityAgent("a2", reply="out_b", delay=0.015),
            node_id="a2", dependencies={"a1"}, successors=set(),
        )
    )
    return await flow.run_flow()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCrewFlowParity:
    """The contract test that keeps the two executors from drifting."""

    async def test_flow_vs_crew_field_parity(self) -> None:
        """Both executors populate the same FlowResult fields, modulo `summary`."""
        crew_result = await _run_crew()
        flow_result = await _run_flow()

        crew_fields = _populated_fields(crew_result)
        flow_fields = _populated_fields(flow_result)

        assert (crew_fields - PARITY_EXEMPT_FIELDS) == (
            flow_fields - PARITY_EXEMPT_FIELDS
        ), _describe_divergence(crew_fields, flow_fields)

        # Guard against the assertion above passing vacuously: the fields
        # FEAT-447 exists to populate must actually be in the compared set.
        for field in ("output", "responses", "nodes", "execution_log",
                      "total_time", "metadata"):
            assert field in flow_fields, (
                f"AgentsFlow left {field!r} at its default — FEAT-447 "
                "regression in _aggregate_result / run_flow wiring."
            )

    async def test_node_execution_info_parity(self) -> None:
        """NodeExecutionInfo carries the same metadata for both executors."""
        crew_result = await _run_crew()
        flow_result = await _run_flow()

        assert crew_result.nodes, "crew produced no NodeExecutionInfo entries"
        assert flow_result.nodes, "flow produced no NodeExecutionInfo entries"

        for label, result in (("crew", crew_result), ("flow", flow_result)):
            for info in result.nodes:
                missing = _unpopulated_node_fields(info)
                assert not missing, (
                    f"{label} node {info.node_id!r} left {missing} unpopulated; "
                    f"the other executor populates them. Fields compared: "
                    f"{list(NODE_PARITY_FIELDS)}"
                )

        # Same *values* where the two executors genuinely must agree: these
        # come from the shared agent stub, not from the orchestration.
        for result in (crew_result, flow_result):
            for info in result.nodes:
                assert info.model == "gpt-4o"
                assert info.provider == "openai"
                assert info.usage["total_tokens"] == 18
                assert info.tool_calls[0]["name"] == "search"
                assert info.client == "FakeOpenAIClient"
                assert info.status == "completed"

    async def test_node_results_parity(self) -> None:
        """`node_results` yields scalars for both executors, never envelopes."""
        crew_result = await _run_crew()
        flow_result = await _run_flow()

        for label, result in (("crew", crew_result), ("flow", flow_result)):
            values = list(result.node_results.values())
            assert values, f"{label} produced no node_results"
            for value in values:
                assert not (isinstance(value, dict) and "response" in value), (
                    f"{label} leaked an AgentNode envelope through "
                    f"node_results: {value!r}"
                )
            # The alias must agree with the primary property.
            assert result.agent_results == result.node_results

    def test_parity_exemptions_are_explicit(self) -> None:
        """PARITY_EXEMPT_FIELDS == {"summary"} — widening it must be deliberate."""
        assert PARITY_EXEMPT_FIELDS == frozenset({"summary"}), (
            "The parity exemption list changed. Adding an exemption means "
            "accepting that the two executors may diverge on that field — "
            "document WHY in the PARITY_EXEMPT_FIELDS comment before "
            "updating this test."
        )
        # Every exempt name must be a real FlowResult field, so a typo can
        # never silently exempt nothing.
        field_names = {f.name for f in dataclasses.fields(FlowResult)}
        assert PARITY_EXEMPT_FIELDS <= field_names

    async def test_flow_summary_stays_empty(self) -> None:
        """The exemption is real: AgentsFlow leaves `summary` empty (AC12)."""
        flow_result = await _run_flow()
        assert flow_result.summary == ""
        # ...and AgentsFlow must not have gained SynthesisMixin.
        assert not any(
            base.__name__ == "SynthesisMixin" for base in AgentsFlow.__mro__
        ), "AgentsFlow gained SynthesisMixin — FEAT-447 Non-Goal violated."
