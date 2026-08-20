"""A generated definition is not just valid — it runs.

Every other test in this package stops at "the compiled definition satisfies
its model's validators". That leaves the most expensive failure mode
uncovered: a definition that parses cleanly and then cannot be built or
executed, because the compiler got a name, a mode or a dependency edge
subtly wrong.

These tests take an authored blueprint all the way through
``AgentCrew.from_definition`` and ``run_flow``/``run_parallel``, using the
repo's sanctioned crew stubs (``DummyAgent`` / ``DummyTool`` from
``tests/_crew_test_helpers``) so no LLM or network is involved. What is
asserted is the part only execution can prove: that the dependency edges the
compiler emitted actually sequenced the agents.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, List, Optional

import pytest

from parrot.bots.flows.authoring.assembler import assemble, to_crew_definition
from parrot.bots.flows.authoring.blueprint import (
    BlueprintNode,
    BlueprintSkeleton,
    BlueprintTransition,
    NodeStub,
)
from parrot.bots.flows.crew.crew import AgentCrew

# tests/_crew_test_helpers.py lives at the tests-root, which is not a package
# path segment for this module.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from _crew_test_helpers import DummyAgent, DummyTool  # noqa: E402


class _DefinitionAgent(DummyAgent):
    """``DummyAgent`` with the constructor ``from_definition`` actually calls.

    ``from_definition`` builds agents as
    ``agent_class(name=..., tools=[...], **agent_def.config)``; the shared
    stub takes neither ``tools`` nor arbitrary config, so this adapts it
    rather than duplicating the stub.
    """

    def __init__(self, name: str, tools: Optional[List[Any]] = None, **config: Any):
        super().__init__(name=name, response=f"[{name}]")
        self.declared_tools = list(tools or [])
        self.config = config
        self.system_prompt: Optional[str] = None


def _blog_blueprint(engine: str = "crew", *, with_transitions: bool = True):
    """The motivating request, as an authored blueprint."""
    skeleton = BlueprintSkeleton(
        name="Blog Publishing Crew",
        description="Research, write and publish a blog post.",
        engine=engine,
        nodes=[
            NodeStub(id="researcher", kind="agent", purpose="Research the topic"),
            NodeStub(id="writer", kind="agent", purpose="Write the post"),
            NodeStub(id="publisher", kind="tool", purpose="Publish the post"),
        ],
    )
    nodes = [
        BlueprintNode(
            id="researcher", kind="agent", system_prompt="You research.",
            tools=["google_search"],
        ),
        BlueprintNode(id="writer", kind="agent", system_prompt="You write."),
        BlueprintNode(
            id="publisher", kind="tool", tool="rest_api",
            kwargs={"url": "https://blog.example/wp-json/wp/v2/posts"},
        ),
    ]
    transitions = (
        [
            BlueprintTransition(source="researcher", target="writer"),
            BlueprintTransition(source="writer", target="publisher"),
        ]
        if with_transitions
        else []
    )
    return assemble(skeleton, nodes, transitions)


def _build_crew(blueprint, tool: Optional[DummyTool] = None) -> AgentCrew:
    """Compile the blueprint and materialise a real ``AgentCrew`` from it."""
    definition = to_crew_definition(blueprint)
    publish_tool = tool or DummyTool(name="rest_api", result={"status": "published"})
    return AgentCrew.from_definition(
        definition,
        class_resolver=lambda _name: _DefinitionAgent,
        tool_resolver=lambda name: publish_tool if name == "rest_api" else None,
        # The wiki is a real platform default, but it writes a SQLite plane
        # under the cwd; these tests are about the graph, not about storage.
        enable_execution_wiki=False,
        # Result persistence is the other storage default, and it is the one
        # that blocks: every `run_*` call writes through ExecutionMemory to a
        # document store, and with no server reachable pymongo hangs in
        # server selection rather than failing — so the four execution tests
        # never terminate, in CI or on a laptop. These tests assert on the
        # graph the blueprint compiled to, not on where its results land.
        persist_results=False,
    )


# ── construction ─────────────────────────────────────────────────────────────

def test_a_generated_definition_builds_a_real_crew():
    crew = _build_crew(_blog_blueprint())

    assert crew.name == "Blog Publishing Crew"
    # Agents and the tool node are all crew members.
    assert {"researcher", "writer", "publisher"} <= set(crew.agents)


def test_authored_system_prompts_reach_the_agents():
    """from_definition applies these through _apply_definition_prompt."""
    crew = _build_crew(_blog_blueprint())

    assert crew.agents["researcher"].system_prompt is not None
    assert "You research." in crew.agents["researcher"].system_prompt


def test_authored_tool_names_reach_the_agent():
    crew = _build_crew(_blog_blueprint())
    assert crew.agents["researcher"].declared_tools == ["google_search"]


def test_an_unresolvable_tool_node_fails_loudly():
    """A tool node is a structural DAG member; skipping it would truncate."""
    blueprint = _blog_blueprint()
    definition = to_crew_definition(blueprint)
    with pytest.raises(ValueError, match="Cannot resolve tool"):
        AgentCrew.from_definition(
            definition,
            class_resolver=lambda _name: _DefinitionAgent,
            tool_resolver=lambda _name: None,
        )


# ── execution ────────────────────────────────────────────────────────────────

async def test_a_generated_crew_executes_end_to_end():
    tool = DummyTool(name="rest_api", result={"status": "published"})
    crew = _build_crew(_blog_blueprint(), tool=tool)

    result = await crew.run_flow("Write about async Python", generate_summary=False)

    assert result is not None
    executed = {info.node_name for info in result.nodes}
    assert {"researcher", "writer", "publisher"} <= executed
    # The deterministic node really invoked its tool.
    assert tool.calls, "the publisher tool node never ran"


async def test_the_compiled_edges_actually_sequence_the_agents():
    """The assertion only execution can make.

    A definition can validate with its dependency edges pointing at names
    nothing resolves — the relations are then dropped and every agent runs
    at once. Checking that the writer saw the researcher's output is what
    proves the edges survived compilation.
    """
    crew = _build_crew(_blog_blueprint())

    await crew.run_flow("Write about async Python", generate_summary=False)

    writer_prompts = " ".join(crew.agents["writer"].prompts_received)
    assert "[researcher]" in writer_prompts, (
        "the writer did not receive the researcher's output, so the "
        "researcher → writer dependency was not wired"
    )


async def test_a_dependency_free_blueprint_runs_in_parallel_mode():
    """No transitions compiles to 'parallel', which run_parallel executes."""
    blueprint = _blog_blueprint(with_transitions=False)
    assert blueprint.execution_mode == "parallel"

    definition = to_crew_definition(blueprint)
    assert definition.execution_mode.value == "parallel"

    crew = _build_crew(blueprint)
    # run_parallel takes one task dict per agent, not a shared prompt.
    result = await crew.run_parallel(
        [
            {"agent_id": "researcher", "query": "Research async Python"},
            {"agent_id": "writer", "query": "Write about async Python"},
        ],
        generate_summary=False,
    )

    executed = {info.node_name for info in result.nodes}
    assert {"researcher", "writer"} <= executed


async def test_a_failing_agent_does_not_abort_the_whole_crew():
    """Whatever the generated crew does, one bad agent must not lose the run."""
    blueprint = _blog_blueprint()
    definition = to_crew_definition(blueprint)

    def _resolver(_name: str):
        class _Failing(_DefinitionAgent):
            def __init__(self, name: str, tools=None, **config):
                super().__init__(name, tools, **config)
                self._fail = name == "writer"

        return _Failing

    crew = AgentCrew.from_definition(
        definition,
        class_resolver=_resolver,
        tool_resolver=lambda name: DummyTool(name="rest_api"),
        enable_execution_wiki=False,
        persist_results=False,
    )
    result = await crew.run_flow("topic", generate_summary=False)

    assert result is not None
    status = getattr(result.status, "value", result.status)
    assert status in {"partial", "failed", "completed"}
    # The researcher ran before the failure and its work is still reported.
    assert any(info.node_name == "researcher" for info in result.nodes)
