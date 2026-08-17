"""The node-by-node authoring loop, driven by a scripted fake client.

The most important test here is
``test_per_node_prompt_does_not_carry_other_nodes_definitions``: the whole
reason for authoring node-by-node is that prompt size stays flat as the
workflow grows, and that property is easy to destroy accidentally by
threading more context into the per-node call.
"""
from __future__ import annotations

import pytest

from parrot.bots.flows.authoring.author import FlowAuthor, FlowAuthoringError
from parrot.bots.flows.authoring.blueprint import BlueprintSkeleton, NodeStub

from .conftest import FakePlannerClient


def _skeleton_payload(engine: str = "crew"):
    return {
        "name": "Blog Pipeline",
        "description": "research then write",
        "engine": engine,
        "nodes": [
            {"id": "researcher", "kind": "agent", "purpose": "Research the topic"},
            {"id": "writer", "kind": "agent", "purpose": "Write the post"},
        ],
    }


def _node_payload(node_id: str, **extra):
    payload = {"id": node_id, "kind": "agent", "system_prompt": f"You are {node_id}."}
    payload.update(extra)
    return payload


def _author(catalog, responses, **kwargs) -> FlowAuthor:
    return FlowAuthor(None, catalog, client=FakePlannerClient(responses), **kwargs)


# ── stages ───────────────────────────────────────────────────────────────────

async def test_skeleton_parses_and_pins_the_requested_engine(crew_catalog):
    # The model labels it "flow"; the caller asked for "crew" and wins.
    payload = _skeleton_payload(engine="flow")
    author = _author(crew_catalog, [payload])
    skeleton = await author.skeleton("build me a blog crew", engine="crew")
    assert skeleton.engine == "crew"
    assert [n.id for n in skeleton.nodes] == ["researcher", "writer"]


async def test_skeleton_is_truncated_to_max_nodes(crew_catalog):
    payload = _skeleton_payload()
    payload["nodes"] = [
        {"id": f"n{i}", "kind": "agent", "purpose": "x"} for i in range(10)
    ]
    author = _author(crew_catalog, [payload], max_nodes=3)
    skeleton = await author.skeleton("many nodes", engine="crew")
    assert len(skeleton.nodes) == 3


async def test_one_llm_call_per_node(crew_catalog):
    skeleton = BlueprintSkeleton(**_skeleton_payload())
    client_responses = [_node_payload("researcher"), _node_payload("writer")]
    author = _author(crew_catalog, client_responses)
    nodes, failed = await author.author_nodes(skeleton)
    assert not failed
    assert len(nodes) == 2
    assert len(author.client.prompts) == 2


async def test_per_node_prompt_does_not_carry_other_nodes_definitions(crew_catalog):
    """Context stays flat: a node sees neighbours as one line, not in full."""
    skeleton = BlueprintSkeleton(**_skeleton_payload())
    author = _author(
        crew_catalog,
        [
            _node_payload("researcher", system_prompt="SENTINEL_RESEARCHER_PROMPT"),
            _node_payload("writer", system_prompt="SENTINEL_WRITER_PROMPT"),
        ],
        concurrency=1,
    )
    await author.author_nodes(skeleton)

    second_prompt = author.client.prompts[1]
    # The other node's authored body must not have leaked into this prompt.
    assert "SENTINEL_RESEARCHER_PROMPT" not in second_prompt
    # But its one-line purpose must be there — neighbours are still context.
    assert "Research the topic" in second_prompt


async def test_node_identity_is_pinned_to_the_stub(crew_catalog):
    """A drifted id is corrected; the skeleton is authoritative."""
    skeleton = BlueprintSkeleton(**_skeleton_payload())
    author = _author(
        crew_catalog,
        [
            _node_payload("wrong_id"),
            _node_payload("writer"),
        ],
        concurrency=1,
    )
    nodes, _ = await author.author_nodes(skeleton)
    assert nodes[0].id == "researcher"
    assert nodes[0].kind == "agent"


async def test_pinning_a_kind_revalidates_the_whole_node(crew_catalog):
    """Forcing `kind` must not smuggle through an invalid field combination.

    ``model_copy`` does not re-run validators, so overwriting a node authored
    as a tool into an agent would leave it carrying `tool` — a combination
    BlueprintNode rejects outright, which would then compile down the agent
    branch with the tool silently discarded.
    """
    skeleton = BlueprintSkeleton(**_skeleton_payload())
    author = _author(
        crew_catalog,
        [
            # Answers the 'researcher' agent stub with a tool node.
            {"id": "researcher", "kind": "tool", "tool": "google_search"},
            _node_payload("writer"),
        ],
        concurrency=1,
    )
    nodes, failed = await author.author_nodes(skeleton)
    # Rejected rather than silently coerced into a malformed agent node.
    assert failed == ["researcher"]
    assert [n.id for n in nodes] == ["writer"]


async def test_a_compatible_kind_drift_is_reconciled(crew_catalog):
    """When the fields do not contradict, pinning succeeds."""
    skeleton = BlueprintSkeleton(**_skeleton_payload())
    author = _author(
        crew_catalog,
        [
            # 'synthesis' carries no kind-specific fields, so re-validating
            # it as the requested 'agent' kind is unambiguous.
            {"id": "researcher", "kind": "synthesis", "title": "R"},
            _node_payload("writer"),
        ],
        concurrency=1,
    )
    nodes, failed = await author.author_nodes(skeleton)
    assert not failed
    assert nodes[0].kind == "agent"


async def test_a_failing_node_is_dropped_not_fatal(crew_catalog):
    """A workflow missing one named step beats no workflow at all."""
    skeleton = BlueprintSkeleton(**_skeleton_payload())
    author = _author(
        crew_catalog,
        ["this is not json", _node_payload("writer")],
        concurrency=1,
    )
    nodes, failed = await author.author_nodes(skeleton)
    assert [n.id for n in nodes] == ["writer"]
    assert failed == ["researcher"]


async def test_transitions_are_skipped_for_a_single_node(crew_catalog):
    skeleton = BlueprintSkeleton(
        name="solo",
        engine="crew",
        nodes=[NodeStub(id="only", kind="agent", purpose="do it")],
    )
    author = _author(crew_catalog, [])
    nodes, _ = [], []
    transitions = await author.author_transitions(
        skeleton, [type("N", (), {"id": "only"})()]
    )
    assert transitions == []
    assert author.client.prompts == []


async def test_transitions_accept_a_bare_array(crew_catalog):
    """Both {"transitions": [...]} and a bare array are natural readings."""
    skeleton = BlueprintSkeleton(**_skeleton_payload())
    author = _author(
        crew_catalog, [[{"source": "researcher", "target": "writer"}]]
    )
    nodes = [type("N", (), {"id": "researcher"})(), type("N", (), {"id": "writer"})()]
    transitions = await author.author_transitions(skeleton, nodes)
    assert len(transitions) == 1
    assert transitions[0].source == "researcher"


async def test_transitions_wrapped_in_an_object(crew_catalog):
    skeleton = BlueprintSkeleton(**_skeleton_payload())
    author = _author(
        crew_catalog,
        [{"transitions": [{"source": "researcher", "target": "writer"}]}],
    )
    nodes = [type("N", (), {"id": "researcher"})(), type("N", (), {"id": "writer"})()]
    assert len(await author.author_transitions(skeleton, nodes)) == 1


# ── parsing ──────────────────────────────────────────────────────────────────

async def test_code_fenced_json_is_accepted(crew_catalog):
    fenced = '```json\n{"name":"x","engine":"crew","nodes":[{"id":"a","kind":"agent","purpose":"p"}]}\n```'
    author = _author(crew_catalog, [fenced])
    skeleton = await author.skeleton("x", engine="crew")
    assert skeleton.name == "x"


async def test_non_json_response_raises_a_typed_error(crew_catalog):
    author = _author(crew_catalog, ["I think you should build a crew!"])
    with pytest.raises(FlowAuthoringError, match="not valid JSON"):
        await author.skeleton("x", engine="crew")


async def test_schema_violating_response_raises_a_typed_error(crew_catalog):
    author = _author(crew_catalog, [{"name": "x", "engine": "crew"}])  # no nodes
    with pytest.raises(FlowAuthoringError, match="validation"):
        await author.skeleton("x", engine="crew")


# ── prompt content ───────────────────────────────────────────────────────────

async def test_node_prompt_carries_the_catalog_slice_for_its_kind(crew_catalog):
    skeleton = BlueprintSkeleton(**_skeleton_payload())
    author = _author(crew_catalog, [_node_payload("researcher")])
    await author.author_node(skeleton.nodes[0], skeleton)
    prompt = author.client.prompts[0]
    assert "google_search" in prompt
    assert "NEVER invent a tool" in prompt


async def test_repair_prompt_embeds_the_validation_report(crew_catalog):
    from parrot.bots.flows.authoring.validator import ValidationIssue

    skeleton = BlueprintSkeleton(**_skeleton_payload())
    author = _author(crew_catalog, [_node_payload("researcher")])
    issue = ValidationIssue("researcher", "tool_not_found", "tool 'nope' is unknown")
    await author.repair_node(skeleton.nodes[0], skeleton, [issue])
    assert "tool 'nope' is unknown" in author.client.prompts[0]
