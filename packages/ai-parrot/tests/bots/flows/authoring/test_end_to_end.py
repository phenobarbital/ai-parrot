"""End-to-end orchestrator runs against a scripted model.

The headline case is the request this feature was designed around:

    "necesito un workflow de un crew de agentes que investigan, redactan un
     tema en formato blog y un último nodo lo publica en wordpress"

There is no WordPress toolkit on this platform, so the interesting assertion
is not that a workflow comes out — it is that the missing capability is
*named* rather than papered over with an invented tool.
"""
from __future__ import annotations

import pytest

from parrot.bots.flows.authoring.catalog import ComponentCatalog
from parrot.bots.flows.authoring.contracts import (
    AuthoringStage,
    AuthoringStatus,
    FlowAuthoringRequest,
)
from parrot.bots.flows.authoring.orchestrator import FlowAuthoringOrchestrator

from .conftest import FakePlannerClient

BLOG_REQUEST = (
    "necesito un workflow de un crew de agentes que investigan, redactan un "
    "tema en formato blog, un revisor SEO lo optimiza y un ultimo nodo lo "
    "publica en wordpress"
)

_SKELETON = {
    "name": "Blog Publishing Crew",
    "description": "Research, write, SEO-review and publish a blog post.",
    "engine": "crew",
    "nodes": [
        {"id": "researcher", "kind": "agent", "purpose": "Research the topic"},
        {"id": "writer", "kind": "agent", "purpose": "Write the blog post"},
        {"id": "seo_reviewer", "kind": "agent", "purpose": "Optimise for SEO"},
        {"id": "publisher", "kind": "tool", "purpose": "Publish the post"},
    ],
}

_NODES = [
    {
        "id": "researcher",
        "kind": "agent",
        "system_prompt": "You research the topic thoroughly.",
        "tools": ["google_search", "web_scraping"],
    },
    {
        "id": "writer",
        "kind": "agent",
        "system_prompt": "You write a blog post from the research.",
    },
    {
        "id": "seo_reviewer",
        "kind": "agent",
        "system_prompt": "You optimise the post for search.",
    },
    {
        "id": "publisher",
        "kind": "tool",
        "tool": "rest_api",
        "kwargs": {"url": "https://blog.example/wp-json/wp/v2/posts"},
    },
]

_TRANSITIONS = {
    "transitions": [
        {"source": "researcher", "target": "writer"},
        {"source": "writer", "target": "seo_reviewer"},
        {"source": "seo_reviewer", "target": "publisher"},
    ]
}


def _orchestrator(catalog: ComponentCatalog, responses) -> FlowAuthoringOrchestrator:
    return FlowAuthoringOrchestrator(
        client=FakePlannerClient(responses), catalog=catalog, concurrency=1
    )


async def test_blog_request_compiles_to_a_valid_crew_definition(crew_catalog):
    orchestrator = _orchestrator(
        crew_catalog, [_SKELETON, *_NODES, _TRANSITIONS]
    )
    result = await orchestrator.build(
        FlowAuthoringRequest(description=BLOG_REQUEST, engine="crew")
    )

    assert result.status is AuthoringStatus.SUCCESS, result.error or result.validation_issues
    assert result.engine == "crew"
    assert result.crew_definition is not None
    assert result.flow_definition is None

    # The compiled payload must satisfy CrewDefinition's own validators.
    from parrot.models.crew_definition import CrewDefinition

    definition = CrewDefinition.model_validate(result.crew_definition)
    assert [a.agent_id for a in definition.agents] == [
        "researcher", "writer", "seo_reviewer",
    ]
    assert [t.node_id for t in definition.tool_nodes] == ["publisher"]
    assert definition.execution_mode.value == "flow"


async def test_every_referenced_tool_exists_in_the_catalog(crew_catalog):
    orchestrator = _orchestrator(crew_catalog, [_SKELETON, *_NODES, _TRANSITIONS])
    result = await orchestrator.build(
        FlowAuthoringRequest(description=BLOG_REQUEST, engine="crew")
    )
    known = crew_catalog.tool_names()
    for node in result.blueprint.nodes:
        assert set(node.tools) <= known
        if node.tool:
            assert node.tool in known


async def test_a_wordpress_tool_is_reported_as_a_gap_not_invented(crew_catalog):
    """The model reaches for a tool that does not exist, twice."""
    invented = dict(_NODES[3], tool="wordpress_publish")
    responses = [
        _SKELETON,
        *_NODES[:3],
        invented,
        _TRANSITIONS,
        # repair round: it doubles down rather than substituting
        invented,
        _TRANSITIONS,
    ]
    result = await _orchestrator(crew_catalog, responses).build(
        FlowAuthoringRequest(description=BLOG_REQUEST, engine="crew")
    )

    assert result.status is AuthoringStatus.FAILED
    gaps = {gap.requested for gap in result.capability_gaps}
    assert "wordpress_publish" in gaps
    # The failure must name the missing capability, not hide it.
    assert any("wordpress_publish" in issue for issue in result.validation_issues)


async def test_a_repaired_node_recovers_the_run(crew_catalog):
    """First attempt invents a tool; the repair round substitutes a real one.

    The run is reported as a clean SUCCESS with ``repair_rounds == 1``, not as
    DEGRADED: gaps describe what the *delivered* workflow lacks, and this one
    lacks nothing. Carrying forward a gap that the repair resolved would tell
    the caller a tool is missing from a workflow that never references it.
    """
    invented = dict(_NODES[3], tool="wordpress_publish")
    responses = [
        _SKELETON,
        *_NODES[:3],
        invented,
        _TRANSITIONS,
        _NODES[3],  # repair: rest_api, which exists
        _TRANSITIONS,
    ]
    result = await _orchestrator(crew_catalog, responses).build(
        FlowAuthoringRequest(description=BLOG_REQUEST, engine="crew")
    )

    assert result.status is AuthoringStatus.SUCCESS, result.error
    assert result.repair_rounds == 1
    assert result.capability_gaps == []
    assert result.crew_definition is not None
    publisher = next(
        node for node in result.blueprint.nodes if node.id == "publisher"
    )
    assert publisher.tool == "rest_api"


async def test_a_lateral_repair_is_rejected_not_shipped(crew_catalog):
    """A repair that swaps one error for another is churn, not progress.

    The first attempt names a tool that does not exist; the repair round
    names a *different* nonexistent tool. Error count is unchanged, so the
    original must be kept — otherwise the caller ends up with a different
    problem than the one already reported to them.
    """
    first = dict(_NODES[3], tool="wordpress_publish")
    second = dict(_NODES[3], tool="medium_publish")
    responses = [
        _SKELETON,
        *_NODES[:3],
        first,
        _TRANSITIONS,
        second,  # repair: still invalid, same count
        _TRANSITIONS,
    ]
    result = await _orchestrator(crew_catalog, responses).build(
        FlowAuthoringRequest(description=BLOG_REQUEST, engine="crew")
    )
    assert result.status is AuthoringStatus.FAILED
    gaps = {gap.requested for gap in result.capability_gaps}
    assert gaps == {"wordpress_publish"}, "the original report must be kept"


async def test_a_dropped_node_degrades_rather_than_failing(crew_catalog):
    responses = [
        _SKELETON,
        _NODES[0],
        "not json at all",  # writer fails to author
        _NODES[2],
        _NODES[3],
        {"transitions": [{"source": "seo_reviewer", "target": "publisher"}]},
    ]
    result = await _orchestrator(crew_catalog, responses).build(
        FlowAuthoringRequest(description=BLOG_REQUEST, engine="crew")
    )
    assert result.status is AuthoringStatus.DEGRADED
    assert result.dropped_nodes == ["writer"]
    assert "writer" not in result.blueprint.node_ids()


async def test_progress_is_reported_for_each_stage(crew_catalog):
    seen = []
    orchestrator = _orchestrator(crew_catalog, [_SKELETON, *_NODES, _TRANSITIONS])
    await orchestrator.build(
        FlowAuthoringRequest(description=BLOG_REQUEST, engine="crew"),
        on_progress=seen.append,
    )
    stages = [progress.stage for progress in seen]
    assert AuthoringStage.SKELETON in stages
    assert AuthoringStage.NODES in stages
    assert AuthoringStage.TRANSITIONS in stages
    # The node stage reports completion counts so a poller can show N/M.
    node_ticks = [p for p in seen if p.stage is AuthoringStage.NODES]
    assert node_ticks[-1].nodes_done == 4
    assert node_ticks[-1].nodes_total == 4


async def test_a_raising_progress_callback_does_not_fail_the_run(crew_catalog):
    def boom(_progress):
        raise RuntimeError("callback exploded")

    result = await _orchestrator(
        crew_catalog, [_SKELETON, *_NODES, _TRANSITIONS]
    ).build(
        FlowAuthoringRequest(description=BLOG_REQUEST, engine="crew"),
        on_progress=boom,
    )
    assert result.status is AuthoringStatus.SUCCESS


async def test_engine_auto_picks_crew_when_no_agents_are_registered(crew_catalog):
    result = await _orchestrator(
        crew_catalog, [_SKELETON, *_NODES, _TRANSITIONS]
    ).build(FlowAuthoringRequest(description=BLOG_REQUEST, engine="auto"))
    assert result.engine == "crew"


async def test_engine_auto_picks_flow_when_agents_exist(catalog):
    """AgentsFlow can only wire agents that already exist, so 'auto' needs some."""
    skeleton = {
        "name": "Research Flow",
        "engine": "flow",
        "nodes": [
            {"id": "researcher", "kind": "agent", "purpose": "Research"},
            {"id": "writer", "kind": "agent", "purpose": "Write"},
        ],
    }
    nodes = [
        {"id": "researcher", "kind": "agent", "agent_ref": "researcher_agent"},
        {"id": "writer", "kind": "agent", "agent_ref": "writer_agent"},
    ]
    transitions = {"transitions": [{"source": "researcher", "target": "writer"}]}
    result = await _orchestrator(catalog, [skeleton, *nodes, transitions]).build(
        FlowAuthoringRequest(description="research then write", engine="auto")
    )
    assert result.engine == "flow"
    assert result.status is AuthoringStatus.SUCCESS, result.error
    assert result.flow_definition is not None
    assert result.crew_definition is None

    from parrot.bots.flows.flow.definition import FlowDefinition

    definition = FlowDefinition.model_validate(result.flow_definition)
    assert {"__start__", "__end__"} <= {node.id for node in definition.nodes}


async def test_no_authored_node_fails_the_run(crew_catalog):
    responses = [_SKELETON, "bad", "bad", "bad", "bad"]
    result = await _orchestrator(crew_catalog, responses).build(
        FlowAuthoringRequest(description=BLOG_REQUEST, engine="crew")
    )
    assert result.status is AuthoringStatus.FAILED
    assert result.error and "No node could be authored" in result.error


async def test_a_malformed_skeleton_fails_cleanly(crew_catalog):
    result = await _orchestrator(crew_catalog, ["not json"]).build(
        FlowAuthoringRequest(description=BLOG_REQUEST, engine="crew")
    )
    assert result.status is AuthoringStatus.FAILED
    assert result.error and "not valid JSON" in result.error


async def test_the_result_is_json_round_trippable(crew_catalog):
    """It is persisted to a Redis-backed job record, so it must survive JSON."""
    import json

    from parrot.bots.flows.authoring.contracts import FlowAuthoringResult

    result = await _orchestrator(
        crew_catalog, [_SKELETON, *_NODES, _TRANSITIONS]
    ).build(FlowAuthoringRequest(description=BLOG_REQUEST, engine="crew"))

    payload = json.loads(json.dumps(result.model_dump(mode="json")))
    assert FlowAuthoringResult.model_validate(payload).status is result.status


# ── code-review fixes (PR #1186) ─────────────────────────────────────────────

class _StubAgent:
    """Satisfies the ``AgentLike`` protocol ``AgentNode.agent`` is typed with."""

    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def invoke(self, prompt: str, **kwargs):  # pragma: no cover - unused
        return ""

    async def ask(self, question: str = "", **kwargs):  # pragma: no cover
        return ""


class _Registry:
    def __init__(self, *names: str) -> None:
        self._agents = {name: _StubAgent(name) for name in names}

    def get_bot_instance(self, name):
        return self._agents.get(name)


def test_an_authored_decision_flow_materializes_end_to_end(catalog):
    """blueprint → FlowDefinition → AgentsFlow, with real voters attached.

    Every hop used to break: the compiled config named no voters, so the
    DecisionNode was built with agents={} and held a vote nobody could win.
    """
    from parrot.bots.flows.authoring.assembler import assemble, to_flow_definition
    from parrot.bots.flows.authoring.blueprint import (
        BlueprintNode,
        BlueprintSkeleton,
        BlueprintTransition,
        NodeStub,
    )
    from parrot.bots.flows.authoring.validator import validate_blueprint
    from parrot.bots.flows.flow.flow import AgentsFlow

    skeleton = BlueprintSkeleton(
        name="Review Gate",
        engine="flow",
        nodes=[
            NodeStub(id="draft", kind="agent", purpose="Draft the answer"),
            NodeStub(id="vote", kind="decision", purpose="Approve or reject"),
        ],
    )
    blueprint = assemble(
        skeleton,
        [
            BlueprintNode(id="draft", kind="agent", agent_ref="writer_agent"),
            BlueprintNode(
                id="vote",
                kind="decision",
                config={
                    "mode": "ballot",
                    "decision_type": "approval",
                    "agent_refs": ["writer_agent", "researcher_agent"],
                },
            ),
        ],
        [BlueprintTransition(source="draft", target="vote")],
    )

    report = validate_blueprint(blueprint, catalog)
    assert report.ok, str(report)

    definition = to_flow_definition(blueprint)
    flow = AgentsFlow.from_definition(
        definition, agent_registry=_Registry("writer_agent", "researcher_agent")
    )
    node = flow._materialize_nodes()["vote"]
    assert node.decision_config.mode.value == "ballot"
    assert set(node.agents) == {"writer_agent", "researcher_agent"}
    # Retries stay opt-in: the authored definition never asked for any.
    assert node.max_retries == 0
