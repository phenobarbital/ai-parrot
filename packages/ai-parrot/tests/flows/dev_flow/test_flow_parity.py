"""Declarative ↔ imperative parity for the dev-flow (FEAT-412, TASK-2127).

The dev-flow is authored declaratively (``build_dev_flow_definition``) but
executed in explicit-edge mode (``build_dev_flow`` re-declares every edge),
because the ``planner`` / ``feature_handoff`` / ``failure_handler`` OR-joins
cannot be fired by the ``from_definition`` AND-join scheduler. That split is
only safe if the two layers agree edge-for-edge — this module is that guard,
modelled on ``test_feature_flow.py::test_definition_parity_feature_mode``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from parrot.flows.dev_flow.definition import build_dev_flow_definition
from parrot.flows.dev_flow.flow import build_dev_flow


def _flow():
    return build_dev_flow(
        dispatcher=MagicMock(),
        redis_url="redis://x",
        publish_flow_events=False,
    )


def _normalize(condition: str) -> str:
    """Declarative ``on_success`` == imperative default ``always``.

    Pre-existing vocabulary difference between the two layers, established by
    the dev_loop topologies (``definition.py``'s ``on_success`` edges become
    bare ``flow.add_edge()`` calls, which default to ``condition="always"``).
    """
    return "always" if condition == "on_success" else condition


# ---------------------------------------------------------------------------
# Parity
# ---------------------------------------------------------------------------


def test_declarative_imperative_parity():
    definition = build_dev_flow_definition()
    flow = _flow()

    assert {n.id for n in definition.nodes} == set(flow._nodes)

    decl_edges = {
        (e.from_, e.to, _normalize(e.condition)) for e in definition.edges
    }
    imp_edges = {(e.from_, e.to, e.condition) for e in flow._edges}
    assert decl_edges == imp_edges

    # Every on_condition edge on BOTH sides actually carries a predicate —
    # a declarative predicate with no imperative twin would silently never
    # route.
    decl_predicated = {
        (e.from_, e.to) for e in definition.edges if e.condition == "on_condition"
    }
    imp_predicated = {
        (e.from_, e.to) for e in flow._edges
        if e.condition == "on_condition" and e.predicate is not None
    }
    assert decl_predicated == imp_predicated


def test_flow_is_named_dev_flow():
    assert _flow().name == "dev-flow"
    custom = build_dev_flow(
        dispatcher=MagicMock(), redis_url="redis://x",
        name="my-dev-flow", publish_flow_events=False,
    )
    assert custom.name == "my-dev-flow"


def test_flow_carries_its_definition():
    flow = _flow()
    assert flow._dev_loop_definition.flow == "dev-flow"


def test_publisher_attached_only_when_requested():
    assert _flow()._event_publisher is None
    published = build_dev_flow(
        dispatcher=MagicMock(), redis_url="redis://x", publish_flow_events=True
    )
    assert published._event_publisher is not None


# ---------------------------------------------------------------------------
# Materialized nodes
# ---------------------------------------------------------------------------


def test_all_ten_nodes_materialize():
    from parrot.flows.dev_flow.nodes.dev_intake import DevIntakeNode
    from parrot.flows.dev_flow.nodes.ideation import IdeationNode

    flow = _flow()
    assert len(flow._nodes) == 10
    assert isinstance(flow._nodes["dev_intake"], DevIntakeNode)
    assert isinstance(flow._nodes["ideation"], IdeationNode)
    # The reused chain materializes the real dev_loop node classes.
    from parrot.flows.dev_loop.nodes.planner import PlannerNode

    assert isinstance(flow._nodes["planner"], PlannerNode)


def test_nodes_carry_edge_derived_dependencies():
    """The factories stamp dependencies/successors from the edge list."""
    flow = _flow()
    assert flow._nodes["ideation"].dependencies == {"dev_intake"}
    # planner's OR-join: both intakes are upstream.
    assert flow._nodes["planner"].dependencies == {"dev_intake", "ideation"}
    assert "planner" in flow._nodes["dev_intake"].successors
    assert "ideation" in flow._nodes["dev_intake"].successors


def test_ideation_receives_max_rounds_and_wiki():
    wiki = MagicMock()
    flow = build_dev_flow(
        dispatcher=MagicMock(), redis_url="redis://x",
        wiki_search=wiki, ideation_max_rounds=5, publish_flow_events=False,
    )
    ideation = flow._nodes["ideation"]
    assert ideation._max_rounds == 5
    assert ideation._wiki_search is wiki


def test_require_plan_approval_reaches_development():
    flow = build_dev_flow(
        dispatcher=MagicMock(), redis_url="redis://x",
        require_plan_approval=True, publish_flow_events=False,
    )
    assert flow._nodes["development"]._require_plan_approval is True
    # Default stays False (per-run shared-state override does the rest).
    assert _flow()._nodes["development"]._require_plan_approval is False


# ---------------------------------------------------------------------------
# Python routing predicates mirror the CEL strings
# ---------------------------------------------------------------------------


def test_python_predicates_match_cel_semantics():
    from parrot.bots.flows.flow.cel_evaluator import CELPredicateEvaluator
    from parrot.flows.dev_flow.definition import (
        _CEL_IS_FEATURE_DOC,
        _CEL_IS_NL_REQUEST,
    )
    from parrot.flows.dev_flow.flow import _is_feature_doc, _is_nl_request

    class _Result:
        def __init__(self, kind):
            self.kind = kind

    for kind, is_nl, is_doc in (
        ("enhancement", True, False),
        ("new_feature", True, False),
        ("feature", False, True),
        ("bug", False, False),
    ):
        result = _Result(kind)
        assert _is_nl_request(result) is is_nl
        assert _is_feature_doc(result) is is_doc
        assert CELPredicateEvaluator(_CEL_IS_NL_REQUEST)(result) is is_nl
        assert CELPredicateEvaluator(_CEL_IS_FEATURE_DOC)(result) is is_doc


def test_intake_fork_predicates_are_mutually_exclusive():
    """Exactly one intake edge may fire for any given brief kind."""
    from parrot.flows.dev_flow.flow import _is_feature_doc, _is_nl_request

    class _Result:
        def __init__(self, kind):
            self.kind = kind

    for kind in ("enhancement", "new_feature", "feature"):
        result = _Result(kind)
        assert sum((_is_nl_request(result), _is_feature_doc(result))) == 1
