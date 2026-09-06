"""Unit tests for the Mermaid Graph codec (FEAT-529 Module 3, TASK-2883)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from parrot.outputs.a2ui.catalog.base import CatalogValidationError
from parrot.outputs.a2ui.graph import (
    GraphEdge,
    GraphGroup,
    GraphNode,
    GraphSpec,
    MermaidCodecError,
    from_mermaid,
    to_mermaid,
)

_FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "mermaid"


def _assert_roundtrip_equal(spec: GraphSpec) -> None:
    """``from_mermaid(to_mermaid(spec)) == spec`` modulo accessibleDescription/size."""
    text = to_mermaid(spec)
    restored = from_mermaid(text)
    original = spec.model_dump(by_alias=True, exclude={"accessible_description", "size"})
    round_tripped = restored.model_dump(by_alias=True, exclude={"accessible_description", "size"})
    assert round_tripped == original, text


class TestMermaidRoundtripFlowchart:
    def test_mermaid_roundtrip_flowchart(self):
        spec = GraphSpec(
            kind="flowchart",
            direction="LR",
            nodes=[
                GraphNode(id="n1", label="Start", shape="circle"),
                # shape=None exercises the "rect" DEFAULT (flowchart's
                # implicit shape) — an explicit "rect" would collapse to
                # None on round-trip too (see mermaid.py's module
                # docstring), so this is the more informative of the two.
                GraphNode(id="n2", label="Do work"),
                GraphNode(id="n3", label="Decide?", shape="diamond"),
                GraphNode(id="n4", label="Cleanup", shape="rounded"),
                GraphNode(id="n5", label="Sub routine", shape="subroutine"),
                GraphNode(id="n6", label="Hex", shape="hexagon"),
                GraphNode(id="n7", label="End", shape="circle"),
            ],
            edges=[
                GraphEdge(**{"from": "n1", "to": "n2", "kind": "solid"}),
                GraphEdge(**{"from": "n2", "to": "n3", "label": "check", "kind": "solid"}),
                GraphEdge(**{"from": "n3", "to": "n4", "label": "no", "kind": "dashed"}),
                GraphEdge(**{"from": "n4", "to": "n5", "kind": "thick"}),
                GraphEdge(**{"from": "n5", "to": "n6", "kind": "solid"}),
                GraphEdge(**{"from": "n6", "to": "n7", "kind": "solid"}),
            ],
            groups=[GraphGroup(id="grp", label="Middle steps", nodes=["n3", "n4"])],
        )
        _assert_roundtrip_equal(spec)

    def test_mermaid_roundtrip_flowchart_default_shape_and_label(self):
        """A node with no explicit shape/label round-trips to shape=None/label=None.

        The edge's ``kind`` is set explicitly (``"solid"``) — unlike shape/
        label, ``kind`` is never collapsed to ``None`` on parse (an edge
        operator is always unambiguously explicit in mermaid text, so
        parsing one always yields a concrete kind; callers who want a
        round-trippable spec set ``kind`` explicitly, same as this fixture).
        """
        spec = GraphSpec(
            nodes=[GraphNode(id="a"), GraphNode(id="b")],
            edges=[GraphEdge(**{"from": "a", "to": "b", "kind": "solid"})],
        )
        _assert_roundtrip_equal(spec)

    def test_mermaid_supports_mid_label_syntax_on_parse(self):
        """from_mermaid() also accepts the '-- text -->' mid-label syntax."""
        text = (_FIXTURES_DIR / "flowchart_mid_label.mmd").read_text()
        expected = json.loads((_FIXTURES_DIR / "flowchart_mid_label.json").read_text())

        spec = from_mermaid(text)
        dumped = spec.model_dump(by_alias=True, exclude_none=True, exclude={"accessible_description", "size"})
        assert dumped == expected


class TestMermaidRoundtripState:
    def test_mermaid_roundtrip_state(self):
        # Node order: `__start__`/`__end__` are placed LAST because they have
        # no top-level textual declaration of their own — they only exist
        # via a `[*]` edge endpoint, so from_mermaid() can only register them
        # the first time an edge references one, which is necessarily after
        # every alias/composite-state declaration has been parsed. Placing
        # them last here keeps this a genuine object round-trip (see
        # `_emit_state`'s docstring comment for the full reasoning).
        spec = GraphSpec(
            kind="state",
            nodes=[
                GraphNode(id="idle", label="Idle State"),
                GraphNode(id="running"),
                GraphNode(id="failed"),
                GraphNode(id="__start__", shape="circle"),
                GraphNode(id="__end__", shape="circle"),
            ],
            edges=[
                GraphEdge(**{"from": "__start__", "to": "idle"}),
                GraphEdge(**{"from": "idle", "to": "running", "label": "start"}),
                GraphEdge(**{"from": "running", "to": "failed", "label": "error"}),
                GraphEdge(**{"from": "running", "to": "__end__"}),
            ],
            groups=[GraphGroup(id="composite", nodes=["running", "failed"])],
        )
        _assert_roundtrip_equal(spec)


class TestMermaidRoundtripSequence:
    def test_mermaid_roundtrip_sequence(self):
        spec = GraphSpec(
            kind="sequence",
            nodes=[
                GraphNode(id="alice", label="Alice"),
                GraphNode(id="bob"),
            ],
            edges=[
                GraphEdge(**{"from": "alice", "to": "bob", "label": "hello", "kind": "solid"}),
                GraphEdge(**{"from": "bob", "to": "alice", "label": "hi back", "kind": "dashed"}),
                GraphEdge(**{"from": "alice", "to": "bob", "label": "bye", "kind": "solid"}),
            ],
        )
        _assert_roundtrip_equal(spec)

        # Order is preserved via the ordered edges list (GraphEdge carries no
        # separate ordering field — spec §2 Data Models is authoritative).
        text = to_mermaid(spec)
        restored = from_mermaid(text)
        assert [(e.from_, e.to, e.label) for e in restored.edges] == [
            (e.from_, e.to, e.label) for e in spec.edges
        ]


class TestMermaidQuotesReservedLabels:
    def test_mermaid_quotes_reserved_labels(self):
        tricky_label = 'Has [brackets], (parens), {braces}, "quotes" and # hash'
        spec = GraphSpec(
            nodes=[GraphNode(id="a", label=tricky_label), GraphNode(id="b")],
            edges=[GraphEdge(**{"from": "a", "to": "b", "label": tricky_label})],
        )
        text = to_mermaid(spec)
        assert '"' in text  # the label got quoted
        assert "#quot;" in text  # embedded quotes escaped

        restored = from_mermaid(text)
        assert restored.nodes[0].label == tricky_label
        assert restored.edges[0].label == tricky_label


class TestMermaidRejectsUnsupportedConstruct:
    @pytest.mark.parametrize(
        "line",
        [
            "classDef someClass fill:#f9f",
            "click n1 callback",
            "style n1 fill:#fff",
            "linkStyle 0 stroke:#333",
            "%%{init: {'theme': 'dark'}}%%",
        ],
    )
    def test_mermaid_rejects_unsupported_construct(self, line):
        text = f"flowchart TB\nn1[A]\nn2[B]\n{line}\nn1 --> n2\n"
        with pytest.raises(MermaidCodecError) as exc:
            from_mermaid(text)
        assert exc.value.line_no == 4
        assert line in exc.value.line

    def test_mermaid_rejects_sequence_loop_block(self):
        text = "sequenceDiagram\nparticipant a\nparticipant b\nloop every day\na->>b: hi\nend\n"
        with pytest.raises(MermaidCodecError) as exc:
            from_mermaid(text)
        assert exc.value.line_no == 4


class TestMermaidIgnoresCommentsAndBlankLines:
    def test_mermaid_ignores_comments_and_blank_lines(self):
        text = "flowchart TB\n%% a comment\n\nn1[A]\n\n%% another\nn2[B]\nn1 --> n2\n"
        spec = from_mermaid(text)
        assert [n.id for n in spec.nodes] == ["n1", "n2"]
        assert len(spec.edges) == 1


class TestMermaidErrorIsCatalogValidationError:
    def test_mermaid_error_is_catalog_validation_error(self):
        assert isinstance(MermaidCodecError(1, "x", "reason"), CatalogValidationError)

    def test_mermaid_error_raised_carries_line_info(self):
        with pytest.raises(MermaidCodecError) as exc:
            from_mermaid("not a real diagram header\n")
        assert exc.value.line_no == 1
        assert exc.value.reason


class TestMermaidReservedStateIdCollision:
    def test_user_authored_start_id_collides(self):
        text = "stateDiagram-v2\n__start__ --> idle\n"
        with pytest.raises(MermaidCodecError, match="reserved"):
            from_mermaid(text)


class TestMermaidEmptySource:
    def test_empty_source_raises(self):
        with pytest.raises(MermaidCodecError):
            from_mermaid("")

    def test_only_comments_raises(self):
        with pytest.raises(MermaidCodecError):
            from_mermaid("%% just a comment\n")
