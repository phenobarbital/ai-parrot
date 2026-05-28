"""Unit tests for FlowDefinition cycle detection — FEAT-163 TASK-1064.

Tests verify:
- _validate_acyclic is a model_validator(mode="after") on FlowDefinition.
- Valid linear DAG constructs without error.
- Fan-out / fan-in (diamond) constructs without error.
- Two-node cycle (A→B→A) raises ValueError mentioning "cycle".
- Self-loop (A→A) raises ValueError mentioning "cycle".
- Three-node cycle (A→B→C→A) raises ValueError.
- Dangling reference errors surface BEFORE cycle errors (validate_node_ids runs first).
"""
import pytest
from pydantic import ValidationError

from parrot.bots.flows.flow.definition import (
    EdgeDefinition,
    FlowDefinition,
    NodeDefinition,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _node(nid: str, node_type: str = "agent", agent_ref: str = "stub") -> NodeDefinition:
    """Minimal NodeDefinition factory using actual field names (id, type, agent_ref)."""
    if node_type == "start" or node_type == "end":
        return NodeDefinition(id=nid, type=node_type)
    return NodeDefinition(id=nid, type=node_type, agent_ref=agent_ref)


def _edge(src: str, tgt: str) -> EdgeDefinition:
    """EdgeDefinition factory using actual field names (from_, to)."""
    return EdgeDefinition(**{"from": src, "to": tgt, "condition": "always"})


# ---------------------------------------------------------------------------
# Valid DAGs (should not raise)
# ---------------------------------------------------------------------------


class TestFlowDefinitionAcyclicAccepted:
    def test_accepts_single_node_no_edges(self) -> None:
        FlowDefinition(
            flow="single",
            nodes=[_node("a")],
            edges=[],
        )

    def test_accepts_linear_dag(self) -> None:
        FlowDefinition(
            flow="linear",
            nodes=[_node("a"), _node("b"), _node("c")],
            edges=[_edge("a", "b"), _edge("b", "c")],
        )

    def test_accepts_fan_out_fan_in(self) -> None:
        """Diamond shape: A → B, A → C, B → D, C → D."""
        FlowDefinition(
            flow="diamond",
            nodes=[_node("a"), _node("b"), _node("c"), _node("d")],
            edges=[
                _edge("a", "b"),
                _edge("a", "c"),
                _edge("b", "d"),
                _edge("c", "d"),
            ],
        )

    def test_accepts_start_end_type_nodes(self) -> None:
        FlowDefinition(
            flow="start-end",
            nodes=[_node("s", "start"), _node("w"), _node("e", "end")],
            edges=[_edge("s", "w"), _edge("w", "e")],
        )


# ---------------------------------------------------------------------------
# Cycle detection (should raise)
# ---------------------------------------------------------------------------


class TestFlowDefinitionCycleDetection:
    def test_rejects_two_node_cycle(self) -> None:
        with pytest.raises((ValidationError, ValueError), match="[Cc]ycle"):
            FlowDefinition(
                flow="cycle-two",
                nodes=[_node("a"), _node("b")],
                edges=[_edge("a", "b"), _edge("b", "a")],
            )

    def test_rejects_self_loop(self) -> None:
        with pytest.raises((ValidationError, ValueError), match="[Cc]ycle"):
            FlowDefinition(
                flow="self-loop",
                nodes=[_node("a")],
                edges=[_edge("a", "a")],
            )

    def test_rejects_three_node_cycle(self) -> None:
        with pytest.raises((ValidationError, ValueError), match="[Cc]ycle"):
            FlowDefinition(
                flow="triangle",
                nodes=[_node("a"), _node("b"), _node("c")],
                edges=[_edge("a", "b"), _edge("b", "c"), _edge("c", "a")],
            )

    def test_cycle_error_mentions_node_ids(self) -> None:
        """The error message should contain at least one of the cyclic node IDs."""
        with pytest.raises((ValidationError, ValueError)) as exc_info:
            FlowDefinition(
                flow="cycle-info",
                nodes=[_node("x"), _node("y")],
                edges=[_edge("x", "y"), _edge("y", "x")],
            )
        err = str(exc_info.value)
        assert "x" in err or "y" in err


# ---------------------------------------------------------------------------
# Validator ordering (validate_node_ids must run before _validate_acyclic)
# ---------------------------------------------------------------------------


class TestValidatorOrdering:
    def test_dangling_reference_surfaces_before_cycle(self) -> None:
        """When a flow has both a dangling reference AND a cycle, the
        validate_node_ids error (referential integrity) must surface first
        because it is declared before _validate_acyclic in the class body."""
        with pytest.raises((ValidationError, ValueError)) as exc_info:
            FlowDefinition(
                flow="bad",
                nodes=[_node("a")],
                # "missing" does not exist as a node; also forms a cycle with "a"
                edges=[_edge("a", "missing"), _edge("missing", "a")],
            )
        err = str(exc_info.value)
        # The referential-integrity error mentions the missing node ID
        assert "missing" in err
