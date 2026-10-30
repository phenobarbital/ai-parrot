"""FEAT-754 M3 — deterministic C4 layout."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from parrot.outputs.a2ui.graph.layout import (
    MAX_STATIC_NODES,
    GraphTooLargeError,
    _group_boxes,
    compute_positions,
)
from parrot.outputs.a2ui.graph.layout_c4 import compute_c4_positions
from parrot.outputs.a2ui.graph.models import GraphSpec, Position

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "c4_container_diagram.json"


def _fixture_spec(**updates: object) -> GraphSpec:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload.update(updates)
    return GraphSpec.model_validate(payload)


def _nested_spec() -> GraphSpec:
    return GraphSpec.model_validate(
        {
            "kind": "c4",
            "level": "component",
            "nodes": [
                {"id": "left", "c4Type": "component"},
                {"id": "right", "c4Type": "component"},
            ],
            "edges": [],
            "groups": [
                {"id": "outer", "nodes": [], "c4Type": "system"},
                {"id": "right-boundary", "parent": "outer", "nodes": ["right"], "c4Type": "container"},
                {"id": "left-boundary", "parent": "outer", "nodes": ["left"], "c4Type": "container"},
            ],
        }
    )


def _contains(
    outer: tuple[float, float, float, float],
    inner: tuple[float, float, float, float],
) -> bool:
    outer_x, outer_y, outer_width, outer_height = outer
    inner_x, inner_y, inner_width, inner_height = inner
    return (
        outer_x <= inner_x
        and outer_y <= inner_y
        and inner_x + inner_width <= outer_x + outer_width
        and inner_y + inner_height <= outer_y + outer_height
    )


def test_c4_layout_deterministic() -> None:
    spec = _fixture_spec()
    assert compute_c4_positions(spec) == compute_c4_positions(spec)


def test_c4_persons_first_tier_externals_last() -> None:
    tb = compute_c4_positions(_fixture_spec(direction="TB"))
    assert tb.positions["customer"].y < tb.positions["web"].y
    assert tb.positions["web"].y < tb.positions["payments"].y

    lr = compute_c4_positions(_fixture_spec(direction="LR"))
    for node_id, tb_position in tb.positions.items():
        assert lr.positions[node_id].x == tb_position.y
        assert lr.positions[node_id].y == tb_position.x


def test_c4_boundaries_nested_boxes_contain_members() -> None:
    result = compute_c4_positions(_nested_spec())
    for group_id, member_id in (("left-boundary", "left"), ("right-boundary", "right")):
        x, y, width, height = result.group_boxes[group_id]
        position = result.positions[member_id]
        assert x <= position.x <= x + width
        assert y <= position.y <= y + height

    assert _contains(result.group_boxes["outer"], result.group_boxes["left-boundary"])
    assert _contains(result.group_boxes["outer"], result.group_boxes["right-boundary"])
    left = result.group_boxes["left-boundary"]
    right = result.group_boxes["right-boundary"]
    assert left[1] + left[3] <= right[1] or right[1] + right[3] <= left[1]


def test_c4_shape_in_row_wraps() -> None:
    nodes = [{"id": f"node-{index}", "c4Type": "container"} for index in range(6)]
    configured = GraphSpec.model_validate(
        {
            "kind": "c4",
            "level": "container",
            "nodes": nodes,
            "edges": [],
            "layout": {"shapeInRow": 3, "boundaryInRow": 2},
        }
    )
    configured_result = compute_c4_positions(configured)
    assert len({position.y for position in configured_result.positions.values()}) == 2
    assert [configured_result.positions[f"node-{index}"].y for index in range(3)] == [20.0] * 3

    default_result = compute_c4_positions(
        GraphSpec.model_validate({"kind": "c4", "level": "container", "nodes": nodes, "edges": []})
    )
    assert len({position.y for position in default_result.positions.values()}) == 2
    assert len({default_result.positions[f"node-{index}"].y for index in range(4)}) == 1


def test_c4_reversed_edges_empty_and_cap() -> None:
    assert compute_c4_positions(_fixture_spec()).reversed_edges == []

    too_many = GraphSpec.model_validate(
        {
            "kind": "c4",
            "level": "container",
            "nodes": [{"id": f"node-{index}", "c4Type": "container"} for index in range(MAX_STATIC_NODES + 1)],
            "edges": [],
        }
    )
    with pytest.raises(GraphTooLargeError):
        compute_c4_positions(too_many)


def test_group_boxes_nested_for_any_kind() -> None:
    spec = _nested_spec()
    positions = {"left": Position(x=40.0, y=40.0), "right": Position(x=40.0, y=120.0)}
    boxes = _group_boxes(spec, positions)
    assert _contains(boxes["outer"], boxes["left-boundary"])
    assert _contains(boxes["outer"], boxes["right-boundary"])


def test_compute_positions_dispatches_c4() -> None:
    spec = _fixture_spec()
    assert compute_positions(spec) == compute_c4_positions(spec)


def test_c4_boundary_box_ignores_person_and_external_members() -> None:
    spec = GraphSpec.model_validate(
        {
            "kind": "c4",
            "level": "container",
            "nodes": [
                {"id": "user", "c4Type": "person"},
                {"id": "api", "c4Type": "container"},
                {"id": "mail", "c4Type": "system_ext"},
            ],
            "edges": [],
            "groups": [{"id": "boundary", "nodes": ["user", "api", "mail"], "c4Type": "system"}],
        }
    )
    result = compute_c4_positions(spec)
    api = result.positions["api"]
    x, y, width, height = result.group_boxes["boundary"]
    assert x < api.x < x + width
    assert y < api.y < y + height
    assert not (x <= result.positions["user"].x <= x + width and y <= result.positions["user"].y <= y + height)
    assert not (x <= result.positions["mail"].x <= x + width and y <= result.positions["mail"].y <= y + height)
