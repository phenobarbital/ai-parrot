"""Unit tests for the ``GraphSpec`` vocabulary (FEAT-529 Module 1, TASK-2882)."""

from __future__ import annotations

import pytest
from parrot.outputs.a2ui.graph import (
    GraphEdge,
    GraphGroup,
    GraphLayout,
    GraphNode,
    GraphSpec,
    Position,
)
from pydantic import ValidationError


def _spec(**overrides):
    defaults = {
        "nodes": [GraphNode(id="a"), GraphNode(id="b")],
        "edges": [GraphEdge(**{"from": "a", "to": "b"})],
    }
    defaults.update(overrides)
    return GraphSpec(**defaults)


class TestGraphSpecRejectsDanglingEdge:
    def test_graphspec_rejects_dangling_edge(self):
        with pytest.raises(ValidationError, match="does not reference an existing node"):
            _spec(edges=[GraphEdge(**{"from": "a", "to": "ghost"})])


class TestGraphSpecRejectsDuplicateNodeIds:
    def test_graphspec_rejects_duplicate_node_ids(self):
        with pytest.raises(ValidationError, match="Duplicate GraphNode id"):
            _spec(nodes=[GraphNode(id="a"), GraphNode(id="a")], edges=[])


class TestGraphSpecDagRejectsCycle:
    def test_graphspec_dag_rejects_cycle(self):
        cyclic_edges = [
            GraphEdge(**{"from": "a", "to": "b"}),
            GraphEdge(**{"from": "b", "to": "a"}),
        ]
        with pytest.raises(ValidationError, match="acyclic"):
            _spec(kind="dag", edges=cyclic_edges)

        # The SAME cyclic shape is legal for the default kind (flowchart).
        _spec(edges=cyclic_edges)  # must not raise

    def test_graphspec_dag_accepts_acyclic(self):
        _spec(kind="dag")  # a -> b only, must not raise


class TestGraphSpecManualRequiresPositions:
    def test_graphspec_manual_requires_positions(self):
        with pytest.raises(ValidationError, match="requires a position for every node"):
            _spec(layout=GraphLayout(engine="manual", positions={"a": Position(x=0, y=0)}))

    def test_graphspec_manual_with_full_positions_passes(self):
        _spec(
            layout=GraphLayout(
                engine="manual",
                positions={"a": Position(x=0, y=0), "b": Position(x=10, y=10)},
            )
        )  # must not raise


class TestGraphSpecSizeAndDescription:
    def test_graphspec_size_and_description(self):
        spec = _spec()
        assert spec.size == "tile"

        with pytest.raises(ValidationError):
            _spec(size="320px")

        described = _spec(accessible_description="A tiny graph.")
        assert described.accessible_description == "A tiny graph."
        dumped = described.model_dump(by_alias=True)
        assert dumped["accessibleDescription"] == "A tiny graph."

        # Round-trips via the wire alias too (populate_by_name=True keeps
        # the snake_case constructor kwarg working above).
        from_wire = GraphSpec.model_validate(
            {
                "nodes": [{"id": "a"}, {"id": "b"}],
                "edges": [{"from": "a", "to": "b"}],
                "accessibleDescription": "Wire round-trip.",
            }
        )
        assert from_wire.accessible_description == "Wire round-trip."


class TestGraphGroupInvariants:
    def test_group_member_must_exist(self):
        with pytest.raises(ValidationError, match="references unknown node"):
            _spec(groups=[GraphGroup(id="g1", nodes=["ghost"])])

    def test_group_member_at_most_one_group(self):
        with pytest.raises(ValidationError, match="belongs to more than one group"):
            _spec(
                groups=[
                    GraphGroup(id="g1", nodes=["a"]),
                    GraphGroup(id="g2", nodes=["a"]),
                ]
            )

    def test_group_valid_passes(self):
        _spec(groups=[GraphGroup(id="g1", nodes=["a", "b"])])  # must not raise


class TestGraphEdgeAliasAndExtraForbid:
    def test_edge_from_alias(self):
        edge = GraphEdge(**{"from": "a", "to": "b"})
        assert edge.from_ == "a"
        assert edge.model_dump(by_alias=True)["from"] == "a"

    def test_edge_populate_by_name(self):
        edge = GraphEdge(from_="a", to="b")
        assert edge.from_ == "a"

    def test_extra_forbidden_on_node(self):
        with pytest.raises(ValidationError):
            GraphNode(id="a", color="red")  # type: ignore[call-arg]

    def test_extra_forbidden_on_spec(self):
        with pytest.raises(ValidationError):
            _spec(fontSize=12)  # type: ignore[call-arg]


class TestNoColourFontPixelVocabulary:
    """Mechanical guard mirroring the spec's schema-level invariant (G9)."""

    def test_no_forbidden_field_names_on_any_graph_model(self):
        forbidden_substrings = ("color", "colour", "font", "px")
        for model in (GraphNode, GraphEdge, GraphGroup, Position, GraphLayout, GraphSpec):
            for field_name in model.model_fields:
                lowered = field_name.lower()
                assert not any(bad in lowered for bad in forbidden_substrings), (
                    f"{model.__name__}.{field_name} looks like styling vocabulary"
                )
