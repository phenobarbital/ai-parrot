"""Unit tests for the deterministic layered layout (FEAT-529 Module 4, TASK-2884)."""

from __future__ import annotations

import pytest
from parrot.outputs.a2ui.graph import (
    MAX_STATIC_NODES,
    GraphEdge,
    GraphGroup,
    GraphNode,
    GraphSpec,
    GraphTooLargeError,
    compute_positions,
)


def _linear_spec(direction: str = "TB") -> GraphSpec:
    return GraphSpec(
        direction=direction,
        nodes=[GraphNode(id="a"), GraphNode(id="b"), GraphNode(id="c")],
        edges=[
            GraphEdge(**{"from": "a", "to": "b"}),
            GraphEdge(**{"from": "b", "to": "c"}),
        ],
    )


class TestLayoutRanksFollowEdges:
    def test_layout_ranks_follow_edges(self):
        spec = GraphSpec(
            nodes=[GraphNode(id="a"), GraphNode(id="b"), GraphNode(id="c"), GraphNode(id="d")],
            edges=[
                GraphEdge(**{"from": "a", "to": "b"}),
                GraphEdge(**{"from": "a", "to": "c"}),
                GraphEdge(**{"from": "b", "to": "d"}),
                GraphEdge(**{"from": "c", "to": "d"}),
            ],
        )
        result = compute_positions(spec)
        reversed_pairs = set(result.reversed_edges)
        for edge in spec.edges:
            if (edge.from_, edge.to) in reversed_pairs:
                continue
            # TB: rank axis is Y — every non-reversed edge must advance Y.
            assert result.positions[edge.to].y > result.positions[edge.from_].y


class TestLayoutDeterministic:
    def test_layout_deterministic(self):
        spec = _linear_spec()
        first = compute_positions(spec)
        second = compute_positions(spec)
        assert first == second


class TestLayoutBreaksCycles:
    def test_layout_breaks_cycles(self):
        spec = GraphSpec(
            nodes=[GraphNode(id="a"), GraphNode(id="b"), GraphNode(id="c")],
            edges=[
                GraphEdge(**{"from": "a", "to": "b"}),
                GraphEdge(**{"from": "b", "to": "c"}),
                GraphEdge(**{"from": "c", "to": "a"}),  # closes the cycle
            ],
        )
        result = compute_positions(spec)
        assert result.reversed_edges  # at least one back edge reported
        assert set(result.positions) == {"a", "b", "c"}  # every node still positioned


class TestLayoutDirectionLrSwapsAxes:
    def test_layout_direction_lr_swaps_axes(self):
        tb = compute_positions(_linear_spec("TB"))
        lr = compute_positions(_linear_spec("LR"))
        for node_id in ("a", "b", "c"):
            tb_pos = tb.positions[node_id]
            lr_pos = lr.positions[node_id]
            assert lr_pos.x == tb_pos.y
            assert lr_pos.y == tb_pos.x


class TestLayoutGroupBoxesContainMembers:
    def test_layout_group_boxes_contain_members(self):
        spec = GraphSpec(
            nodes=[GraphNode(id="a"), GraphNode(id="b"), GraphNode(id="c")],
            edges=[
                GraphEdge(**{"from": "a", "to": "b"}),
                GraphEdge(**{"from": "b", "to": "c"}),
            ],
            groups=[GraphGroup(id="g1", nodes=["a", "b"])],
        )
        result = compute_positions(spec)
        box_x, box_y, box_w, box_h = result.group_boxes["g1"]
        for member_id in ("a", "b"):
            pos = result.positions[member_id]
            assert box_x <= pos.x <= box_x + box_w
            assert box_y <= pos.y <= box_y + box_h


class TestLayoutTooLargeRaises:
    def test_layout_too_large_raises(self):
        nodes = [GraphNode(id=f"n{i}") for i in range(MAX_STATIC_NODES + 1)]
        spec = GraphSpec(nodes=nodes, edges=[])
        with pytest.raises(GraphTooLargeError) as exc:
            compute_positions(spec)
        assert exc.value.node_count == MAX_STATIC_NODES + 1

    def test_layout_at_cap_does_not_raise(self):
        nodes = [GraphNode(id=f"n{i}") for i in range(MAX_STATIC_NODES)]
        spec = GraphSpec(nodes=nodes, edges=[])
        compute_positions(spec)  # must not raise


class TestLayoutMiscInvariants:
    def test_every_node_gets_a_position(self):
        spec = _linear_spec()
        result = compute_positions(spec)
        assert set(result.positions) == {"a", "b", "c"}

    def test_isolated_node_gets_a_position(self):
        spec = GraphSpec(nodes=[GraphNode(id="lonely")], edges=[])
        result = compute_positions(spec)
        assert "lonely" in result.positions
        assert result.width > 0
        assert result.height > 0

    def test_bt_and_rl_mirror_the_rank_axis(self):
        tb = compute_positions(_linear_spec("TB"))
        bt = compute_positions(_linear_spec("BT"))
        # Same cross-axis (x), mirrored rank-axis (y): a is first in TB
        # (smallest y) and last in BT (largest y).
        assert bt.positions["a"].y > bt.positions["c"].y
        assert tb.positions["a"].y < tb.positions["c"].y
