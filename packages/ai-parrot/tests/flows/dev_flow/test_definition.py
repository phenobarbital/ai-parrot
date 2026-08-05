"""Declarative dev-flow definition tests (FEAT-412, TASK-2127).

Pins the node/edge inventory of spec §2 exactly: the two dev-flow intake
nodes plus the eight reused ``dev_loop`` nodes, the intake fork's CEL
predicates, the reused chain's predicates (which must stay identical to
feature-mode's), and the deliberate ABSENCE of every operations node.
"""

from __future__ import annotations

from parrot.flows.dev_flow.definition import build_dev_flow_definition

# The exact 10-node inventory (spec §2 New Public Interfaces).
_EXPECTED_TYPES = {
    "dev_flow.dev_intake",
    "dev_flow.ideation",
    "dev_loop.planner",
    "dev_loop.development",
    "dev_loop.synthesis",
    "dev_loop.qa",
    "dev_loop.feedback_router",
    "dev_loop.feature_handoff",
    "dev_loop.failure_handler",
    "dev_loop.close",
}


def _defn():
    return build_dev_flow_definition()


def _edges(defn):
    return {(e.from_, e.to, e.condition) for e in defn.edges}


# ---------------------------------------------------------------------------
# Validity + inventory
# ---------------------------------------------------------------------------


def test_definition_validates():
    """Construction runs FlowDefinition's own validation (incl. acyclicity)."""
    defn = _defn()
    assert defn.flow == "dev-flow"
    assert defn.description
    assert len(defn.nodes) == 10


def test_node_inventory_matches_spec():
    defn = _defn()
    assert {n.type for n in defn.nodes} == _EXPECTED_TYPES
    # Node ids are the types' short names.
    assert {n.id for n in defn.nodes} == {
        "dev_intake", "ideation", "planner", "development", "synthesis",
        "qa", "feedback_router", "feature_handoff", "failure_handler", "close",
    }
    # No duplicates.
    assert len({n.id for n in defn.nodes}) == len(defn.nodes)


def test_no_ops_nodes_present():
    """dev-flow front-loads no operations concerns (spec §2 Overview)."""
    defn = _defn()
    ids = {n.id for n in defn.nodes}
    types = {n.type for n in defn.nodes}
    for absent in (
        "bug_intake", "research", "deployment_handoff", "revision_handoff",
        "intent_classifier",
    ):
        assert absent not in ids
        assert f"dev_loop.{absent}" not in types


# ---------------------------------------------------------------------------
# Intake fork
# ---------------------------------------------------------------------------


def test_intake_fork_edges_and_predicates():
    defn = _defn()
    by_pair = {
        (e.from_, e.to): e for e in defn.edges if e.condition == "on_condition"
    }

    nl_edge = by_pair[("dev_intake", "ideation")]
    assert nl_edge.predicate == (
        'result.kind == "enhancement" || result.kind == "new_feature"'
    )

    doc_edge = by_pair[("dev_intake", "planner")]
    assert doc_edge.predicate == 'result.kind == "feature"'


def test_ideation_merges_into_planner_on_success():
    defn = _defn()
    assert ("ideation", "planner", "on_success") in _edges(defn)


def test_planner_is_an_or_join():
    """Two predecessors — this is why explicit-edge execution is mandatory."""
    defn = _defn()
    preds = {e.from_ for e in defn.edges if e.to == "planner"}
    assert preds == {"dev_intake", "ideation"}


# ---------------------------------------------------------------------------
# Reused FEAT-378 chain
# ---------------------------------------------------------------------------


def test_reused_chain_edges():
    defn = _defn()
    edges = _edges(defn)
    for pair in (
        ("planner", "development"),
        ("development", "synthesis"),
        ("synthesis", "qa"),
        ("feature_handoff", "close"),
    ):
        assert (*pair, "on_success") in edges


def test_edge_predicates_match_feature_mode_verbatim():
    """The reused chain's CEL strings must be identical to feature-mode's."""
    from parrot.flows.dev_loop.definition import (
        _CEL_FEEDBACK_ACCEPT,
        _CEL_FEEDBACK_ESCALATE,
        _CEL_FEEDBACK_RETRY,
        _CEL_QA_FAILED,
        _CEL_QA_PASSED,
    )

    defn = _defn()
    by_pair = {
        (e.from_, e.to): e.predicate
        for e in defn.edges
        if e.condition == "on_condition"
    }
    assert by_pair[("qa", "feature_handoff")] == _CEL_QA_PASSED
    assert by_pair[("qa", "feedback_router")] == _CEL_QA_FAILED
    assert by_pair[("feedback_router", "failure_handler")] == _CEL_FEEDBACK_ESCALATE
    assert by_pair[("feedback_router", "feature_handoff")] == _CEL_FEEDBACK_ACCEPT
    assert by_pair[("feedback_router", "development")] == _CEL_FEEDBACK_RETRY
    # Sanity: these are the literal strings the spec quotes.
    assert by_pair[("qa", "feature_handoff")] == "result.passed == true"
    assert by_pair[("feedback_router", "development")] == (
        'result.decision == "retry"'
    )


def test_qa_routes_to_exactly_two_targets():
    """Feature-mode QA routing: passed -> handoff, failed -> feedback_router.

    Notably NOT the bug-mode `qa -> development` / `qa -> failure_handler`
    retry pair — in this chain the repair loop is driven by the router.
    """
    defn = _defn()
    qa_conditional = {
        e.to for e in defn.edges
        if e.from_ == "qa" and e.condition == "on_condition"
    }
    assert qa_conditional == {"feature_handoff", "feedback_router"}


def test_repair_loop_back_edge_present():
    defn = _defn()
    assert ("feedback_router", "development", "on_condition") in _edges(defn)


def test_feature_handoff_is_an_or_join():
    defn = _defn()
    preds = {
        e.from_ for e in defn.edges
        if e.to == "feature_handoff" and e.condition != "on_error"
    }
    assert preds == {"qa", "feedback_router"}


# ---------------------------------------------------------------------------
# on_error fan-in
# ---------------------------------------------------------------------------


def test_on_error_fan_in_covers_every_middle_node():
    defn = _defn()
    sources = {
        e.from_ for e in defn.edges
        if e.to == "failure_handler" and e.condition == "on_error"
    }
    assert sources == {
        "dev_intake", "ideation", "planner", "development", "synthesis",
        "qa", "feedback_router", "feature_handoff",
    }
    # The terminals themselves have no on_error edge.
    assert "close" not in sources
    assert "failure_handler" not in sources


def test_every_on_condition_edge_has_a_predicate():
    defn = _defn()
    for edge in defn.edges:
        if edge.condition == "on_condition":
            assert edge.predicate, f"{edge.from_}->{edge.to} lacks a predicate"


def test_edge_count_is_exact():
    """13 routing edges + 8 on_error edges."""
    defn = _defn()
    routing = [e for e in defn.edges if e.condition != "on_error"]
    on_error = [e for e in defn.edges if e.condition == "on_error"]
    assert len(routing) == 12
    assert len(on_error) == 8
    assert len(defn.edges) == 20


def test_definition_is_deterministic():
    """Pure function: no env reads, same output every call."""
    first, second = _defn(), _defn()
    assert _edges(first) == _edges(second)
    assert [n.id for n in first.nodes] == [n.id for n in second.nodes]
