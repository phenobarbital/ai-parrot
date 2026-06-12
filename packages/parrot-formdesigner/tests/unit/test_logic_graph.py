"""Unit tests for FEAT-301 LogicGraph.

Tests cover:
- Topological ordering (fields in evaluation order).
- Cycle detection (CyclicDependencyError raised + graceful degradation).
- Build from FormSchema (only FieldRefCondition creates edges).
"""

from __future__ import annotations

import pytest

from parrot_formdesigner.core.constraints import (
    ConditionOperator,
    DependencyRule,
    FieldRefCondition,
    LocationVarCondition,
)
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.logic_graph import CyclicDependencyError, LogicGraph


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _field(fid: str, rule: DependencyRule | None = None) -> FormField:
    """Build a simple text FormField."""
    return FormField(
        field_id=fid,
        field_type=FieldType.TEXT,
        label={"en": fid},
        depends_on=rule,
    )


def _form(*fields: FormField) -> FormSchema:
    """Build a minimal FormSchema."""
    return FormSchema(
        form_id="test",
        title={"en": "T"},
        sections=[FormSection(section_id="s1", title={"en": "S"}, fields=list(fields))],
    )


def _ref_rule(field_id: str, value: str = "y") -> DependencyRule:
    """Build a simple EQ DependencyRule referencing another field."""
    return DependencyRule(
        conditions=[
            FieldRefCondition(field_id=field_id, operator=ConditionOperator.EQ, value=value)
        ],
    )


# ---------------------------------------------------------------------------
# LogicGraph.build()
# ---------------------------------------------------------------------------

class TestLogicGraphBuild:
    """Tests for LogicGraph.build()."""

    def test_build_no_dependencies(self) -> None:
        """Form with no depends_on → all nodes present, no edges."""
        form = _form(_field("q1"), _field("q2"), _field("q3"))
        graph = LogicGraph.build(form)
        order = graph.topological_order()
        assert set(order) == {"q1", "q2", "q3"}

    def test_build_simple_dependency(self) -> None:
        """q2 depends on q1 → q1 must come before q2."""
        form = _form(_field("q1"), _field("q2", _ref_rule("q1")))
        graph = LogicGraph.build(form)
        order = graph.topological_order()
        assert order.index("q1") < order.index("q2")

    def test_build_location_var_no_edge(self) -> None:
        """LocationVarCondition does NOT create an intra-form edge."""
        loc_rule = DependencyRule(
            conditions=[LocationVarCondition(
                source="location_variable",
                key="store_type",
                operator=ConditionOperator.EQ,
                value="flagship",
            )],
        )
        form = _form(_field("q1"), _field("q2", loc_rule))
        graph = LogicGraph.build(form)
        # q2 has a rule but no intra-form dependency → both in nodes
        order = graph.topological_order()
        assert set(order) == {"q1", "q2"}
        # No ordering constraint between them
        assert "q1" in order and "q2" in order

    def test_build_chain_q1_q2_q3(self) -> None:
        """Chain q1 → q2 → q3 evaluates in topological order."""
        form = _form(
            _field("q1"),
            _field("q2", _ref_rule("q1")),
            _field("q3", _ref_rule("q2")),
        )
        graph = LogicGraph.build(form)
        order = graph.topological_order()
        assert order.index("q1") < order.index("q2") < order.index("q3")

    def test_external_field_ref_no_crash(self) -> None:
        """FieldRefCondition referencing a non-existent field is ignored."""
        rule = DependencyRule(
            conditions=[FieldRefCondition(field_id="non_existent", operator=ConditionOperator.EQ, value="y")],
        )
        form = _form(_field("q1"), _field("q2", rule))
        graph = LogicGraph.build(form)
        # Should not crash — external refs are excluded from graph edges
        order = graph.topological_order()
        assert set(order) == {"q1", "q2"}


# ---------------------------------------------------------------------------
# LogicGraph.topological_order()
# ---------------------------------------------------------------------------

class TestTopologicalOrder:
    """Tests for topological ordering."""

    def test_single_node(self) -> None:
        """Single-node graph returns that node."""
        form = _form(_field("q1"))
        graph = LogicGraph.build(form)
        assert graph.topological_order() == ["q1"]

    def test_diamond_dependency(self) -> None:
        """Diamond: q1 → q2,q3 → q4. q4 must come after q2 and q3."""
        form = _form(
            _field("q1"),
            _field("q2", _ref_rule("q1")),
            _field("q3", _ref_rule("q1")),
            _field("q4", DependencyRule(conditions=[
                FieldRefCondition(field_id="q2", operator=ConditionOperator.EQ, value="y"),
                FieldRefCondition(field_id="q3", operator=ConditionOperator.EQ, value="y"),
            ])),
        )
        graph = LogicGraph.build(form)
        order = graph.topological_order()
        assert order.index("q1") < order.index("q2")
        assert order.index("q1") < order.index("q3")
        assert order.index("q2") < order.index("q4")
        assert order.index("q3") < order.index("q4")

    def test_parallel_independent_fields(self) -> None:
        """Fields with no deps between them can appear in any relative order."""
        form = _form(_field("a"), _field("b"), _field("c"))
        graph = LogicGraph.build(form)
        order = graph.topological_order()
        assert set(order) == {"a", "b", "c"}
        assert len(order) == 3


# ---------------------------------------------------------------------------
# Cycle detection
# ---------------------------------------------------------------------------

class TestCycleDetection:
    """Tests for cycle detection."""

    def test_simple_cycle_raises(self) -> None:
        """q1 → q2 → q1 raises CyclicDependencyError."""
        form = _form(
            _field("q1", _ref_rule("q2")),
            _field("q2", _ref_rule("q1")),
        )
        graph = LogicGraph.build(form)
        with pytest.raises(CyclicDependencyError) as exc_info:
            graph.topological_order()
        assert "q1" in exc_info.value.cycle or "q2" in exc_info.value.cycle

    def test_detect_cycles_returns_cycles(self) -> None:
        """detect_cycles() returns cycle list without raising."""
        form = _form(
            _field("q1", _ref_rule("q2")),
            _field("q2", _ref_rule("q1")),
        )
        graph = LogicGraph.build(form)
        cycles = graph.detect_cycles()
        assert len(cycles) >= 1
        assert any(len(c) >= 2 for c in cycles)

    def test_no_cycle_detect_cycles_empty(self) -> None:
        """detect_cycles() returns empty list when no cycles."""
        form = _form(
            _field("q1"),
            _field("q2", _ref_rule("q1")),
            _field("q3", _ref_rule("q2")),
        )
        graph = LogicGraph.build(form)
        cycles = graph.detect_cycles()
        assert cycles == []

    def test_cycle_error_message(self) -> None:
        """CyclicDependencyError message contains the cycle."""
        form = _form(
            _field("x", _ref_rule("y")),
            _field("y", _ref_rule("x")),
        )
        graph = LogicGraph.build(form)
        with pytest.raises(CyclicDependencyError) as exc_info:
            graph.topological_order()
        assert " -> " in str(exc_info.value)

    def test_three_node_cycle(self) -> None:
        """q1 → q2 → q3 → q1 is detected."""
        form = _form(
            _field("q1", _ref_rule("q3")),
            _field("q2", _ref_rule("q1")),
            _field("q3", _ref_rule("q2")),
        )
        graph = LogicGraph.build(form)
        with pytest.raises(CyclicDependencyError):
            graph.topological_order()
