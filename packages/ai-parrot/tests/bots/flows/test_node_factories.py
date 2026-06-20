"""Unit tests for ``AgentsFlow.from_definition(node_factories=...)`` — FEAT-250 TASK-001.

These tests verify the generic engine hook that lets custom (non
``agent``/``start``/``end``) node types be materialized via an injected
factory closing over live dependencies, while keeping full backward
compatibility when ``node_factories`` is omitted.
"""
from __future__ import annotations

from typing import Set

from pydantic import Field

from parrot.bots.flows.flow.flow import AgentsFlow, register_node, NODE_REGISTRY
from parrot.bots.flows.flow.definition import (
    FlowDefinition,
    NodeDefinition,
    EdgeDefinition,
)
from parrot.bots.flows.core.node import Node


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class StubRegistry:
    """Minimal AgentRegistry stub (mirrors AgentRegistry.get_bot_instance)."""

    def __init__(self, agents: dict | None = None) -> None:
        self._agents = agents or {}

    def get_bot_instance(self, name: str) -> object:
        return self._agents.get(name)


@register_node("test.custom")
class _Custom(Node):
    """A custom node type used only by these tests."""

    injected: object = None
    dependencies: Set[str] = Field(default_factory=set)
    successors: Set[str] = Field(default_factory=set)

    @property
    def name(self) -> str:  # pragma: no cover - trivial
        return self.node_id

    async def execute(self, ctx, deps, **kwargs):  # pragma: no cover - unused
        return {"injected": self.injected}


def _custom_def() -> FlowDefinition:
    """start → c (test.custom) → end."""
    return FlowDefinition(
        flow="t",
        nodes=[
            NodeDefinition(id="start", type="start"),
            NodeDefinition(id="c", type="test.custom"),
            NodeDefinition(id="end", type="end"),
        ],
        edges=[
            EdgeDefinition(**{"from": "start"}, to="c", condition="always"),
            EdgeDefinition(**{"from": "c"}, to="end", condition="always"),
        ],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_node_definition_accepts_registered_custom_type():
    """``NodeDefinition.type`` no longer rejects a registered custom type."""
    nd = NodeDefinition(id="c", type="test.custom")
    assert nd.type == "test.custom"
    assert "test.custom" in NODE_REGISTRY


def test_from_definition_uses_node_factories():
    """A custom node type is built via its factory with an injected dependency."""
    sentinel = object()

    def factory(node_def, deps, succs):
        return _Custom(node_id=node_def.id, injected=sentinel,
                       dependencies=deps, successors=succs)

    flow = AgentsFlow.from_definition(
        _custom_def(),
        agent_registry=StubRegistry(),
        node_factories={"test.custom": factory},
    )
    nodes = flow._materialize_nodes()
    assert isinstance(nodes["c"], _Custom)
    assert nodes["c"].injected is sentinel
    # deps/succs are mirrored from the edges, like the agent branch.
    assert nodes["c"].dependencies == {"start"}
    assert nodes["c"].successors == {"end"}


def test_from_definition_factory_fresh_per_run():
    """Each materialization invokes the factory afresh (no shared instance)."""
    calls: list[int] = []

    def factory(node_def, deps, succs):
        calls.append(1)
        return _Custom(node_id=node_def.id, injected=object(),
                       dependencies=deps, successors=succs)

    flow = AgentsFlow.from_definition(
        _custom_def(),
        agent_registry=StubRegistry(),
        node_factories={"test.custom": factory},
    )
    first = flow._materialize_nodes()
    second = flow._materialize_nodes()
    assert first["c"] is not second["c"]
    assert first["c"].injected is not second["c"].injected
    assert len(calls) == 2


def test_from_definition_without_factories_is_backward_compatible():
    """Omitting ``node_factories`` reproduces the generic construction path."""
    flow = AgentsFlow.from_definition(
        _custom_def(),
        agent_registry=StubRegistry(),
    )
    assert flow._node_factories == {}
    nodes = flow._materialize_nodes()
    # No factory → generic NODE_REGISTRY construction is used.
    assert isinstance(nodes["c"], _Custom)
    assert nodes["c"].injected is None


def test_start_end_nodes_unaffected_by_factories():
    """start/end nodes are still built by the dedicated branch, not factories."""
    def factory(node_def, deps, succs):  # pragma: no cover - must not run for start/end
        raise AssertionError("factory should not be called for start/end")

    flow = AgentsFlow.from_definition(
        _custom_def(),
        agent_registry=StubRegistry(),
        node_factories={"start": factory, "end": factory},
    )
    nodes = flow._materialize_nodes()
    # start/end are handled by their own branch regardless of any factory map.
    assert nodes["start"].node_id == "start"
    assert nodes["end"].node_id == "end"
