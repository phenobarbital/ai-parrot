"""FEAT-754 M1 — C4 vocabulary and validators V1–V7 on GraphSpec."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from parrot.outputs.a2ui.graph.models import GraphSpec

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "c4_container_diagram.json"


def _c4() -> dict:
    return json.loads(FIXTURE.read_text())


def test_fixture_validates() -> None:
    spec = GraphSpec.model_validate(_c4())
    assert spec.kind == "c4" and spec.level == "container"


def test_c4_requires_level_and_c4_type() -> None:
    missing_level = _c4()
    del missing_level["level"]
    with pytest.raises(ValidationError, match="requires level"):
        GraphSpec.model_validate(missing_level)

    missing_type = _c4()
    del missing_type["nodes"][0]["c4Type"]
    with pytest.raises(ValidationError, match="customer"):
        GraphSpec.model_validate(missing_type)


def test_c4_fields_rejected_on_other_kinds() -> None:
    graph = _c4()
    graph["kind"] = "flowchart"
    graph.pop("level")
    for node in graph["nodes"]:
        node.pop("c4Type")
    graph["edges"][-1].pop("hint")
    graph["edges"][2].pop("bidirectional")
    graph["groups"][0].pop("c4Type")
    graph["nodes"][0]["technology"] = "allowed outside c4"
    GraphSpec.model_validate(graph)

    invalid_c4_fields = (
        ("level", lambda data: data.update(level="container")),
        ("node.c4Type", lambda data: data["nodes"][0].update(c4Type="person")),
        ("edge.hint", lambda data: data["edges"][0].update(hint="left")),
        ("edge.bidirectional", lambda data: data["edges"][0].update(bidirectional=False)),
        ("group.parent", lambda data: data["groups"][0].update(parent="platform")),
        ("group.c4Type", lambda data: data["groups"][0].update(c4Type="system")),
        ("layout.shapeInRow", lambda data: data.update(layout={"shapeInRow": 2, "boundaryInRow": 2})),
    )
    for field, add_field in invalid_c4_fields:
        candidate = json.loads(json.dumps(graph))
        add_field(candidate)
        with pytest.raises(ValidationError, match="only valid for kind='c4'"):
            GraphSpec.model_validate(candidate)


def test_group_parent_must_exist_and_be_acyclic() -> None:
    graph = _c4()
    graph["groups"] = [
        {"id": "root", "nodes": [], "c4Type": "system"},
        {"id": "child", "nodes": [], "parent": "missing", "c4Type": "container"},
    ]
    with pytest.raises(ValidationError, match="unknown group"):
        GraphSpec.model_validate(graph)

    graph["groups"][1]["parent"] = "root"
    graph["groups"][0]["parent"] = "child"
    with pytest.raises(ValidationError, match="parent cycle"):
        GraphSpec.model_validate(graph)

    graph["groups"] = [
        {"id": "duplicate", "nodes": []},
        {"id": "duplicate", "nodes": []},
    ]
    with pytest.raises(ValidationError, match="Duplicate GraphGroup"):
        GraphSpec.model_validate(graph)


def test_shape_in_row_and_boundary_in_row_together() -> None:
    graph = _c4()
    graph["layout"] = {"shapeInRow": 2}
    with pytest.raises(ValidationError, match="must be set together"):
        GraphSpec.model_validate(graph)

    graph["layout"] = {"shapeInRow": 0, "boundaryInRow": 2}
    with pytest.raises(ValidationError):
        GraphSpec.model_validate(graph)


def test_dynamic_rejects_hint_and_bidirectional() -> None:
    graph = _c4()
    graph["level"] = "dynamic"
    with pytest.raises(ValidationError, match="level='dynamic'"):
        GraphSpec.model_validate(graph)


def test_c4_rejects_bidirectional_hint_and_person_system_technology() -> None:
    graph = _c4()
    graph["edges"][2]["hint"] = "left"
    with pytest.raises(ValidationError, match="bidirectional"):
        GraphSpec.model_validate(graph)

    graph = _c4()
    graph["nodes"][0]["technology"] = "human"
    with pytest.raises(ValidationError, match="cannot specify technology"):
        GraphSpec.model_validate(graph)


def test_c4_rejects_neighbor_hints() -> None:
    graph = _c4()
    graph["edges"][-1]["hint"] = "neighbor"
    with pytest.raises(ValidationError):
        GraphSpec.model_validate(graph)


def test_c4_node_state_still_works() -> None:
    graph = _c4()
    graph["nodes"][0]["state"] = "failed"
    assert GraphSpec.model_validate(graph).nodes[0].state == "failed"
