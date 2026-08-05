"""Declarative dev-flow topology (FEAT-412).

Authors the ``dev-flow`` graph as a :class:`FlowDefinition` — the
reference/validation/visualization source. Actual execution happens in the
engine's **explicit-edge mode** (``build_dev_flow`` in ``flow.py``
re-declares every edge imperatively) because the graph contains OR-joins the
``from_definition`` AND-join scheduler cannot fire:

* ``planner`` has TWO predecessors — ``dev_intake`` (a ``feature`` intake
  whose document already exists) and ``ideation`` (a natural-language intake
  whose document was just written).
* ``feature_handoff`` has two (``qa`` on pass, ``feedback_router`` on
  ``accept_with_notes``) and ``failure_handler`` is the on-error fan-in.

Same engine limitation documented in ``dev_loop/definition.py``.

Topology (spec §2 Component Diagram)::

    dev_intake ─(enhancement|new_feature)→ ideation ─┐
         └──────(feature)─────────────────────────────┤
                                                      ▼
    planner → development → synthesis → qa ─(passed)→ feature_handoff → close
                    ↑                    │                  ▲
                    └─(retry, bounded)───┤                  │
                                         ▼                  │
                                  feedback_router ──(accept_with_notes)
                                         ├─(escalate)→ failure_handler
                              (+ on_error fan-in from every middle node)

Everything from ``planner`` onward is byte-identical in behavior to the
FEAT-378 feature-mode graph: the same reused ``dev_loop.*`` node types, the
same CEL predicates (imported, not re-spelled, so the two graphs cannot
silently drift), and the same bounded repair loop — whose stop rule lives in
``FeedbackRouterNode._retry_allowed()``, not on the edge.

This module is pure: no env reads at import time.
"""

from __future__ import annotations

from parrot.bots.flows.flow.definition import (
    EdgeDefinition,
    FlowDefinition,
    NodeDefinition,
)

# Reuse the feature-mode node ids and CEL predicates verbatim. Importing them
# (rather than re-declaring the strings) is deliberate: it makes a divergence
# between the feature-mode chain and the dev-flow chain a compile-time
# impossibility instead of a copy-paste hazard.
from parrot.flows.dev_loop.definition import (
    _CEL_FEEDBACK_ACCEPT,
    _CEL_FEEDBACK_ESCALATE,
    _CEL_FEEDBACK_RETRY,
    _CEL_QA_FAILED,
    _CEL_QA_PASSED,
    CLOSE,
    DEVELOPMENT,
    FAILURE,
    FEATURE_HANDOFF,
    FEEDBACK_ROUTER,
    PLANNER,
    QA,
    SYNTHESIS,
)

# Dev-flow's own intake node ids (node id == the type's short name).
DEV_INTAKE = "dev_intake"
IDEATION = "ideation"

# CEL routing predicates for the intake fork (spec §2). The two
# natural-language intents go to ideation; a document intake goes straight to
# the planner.
_CEL_IS_NL_REQUEST = 'result.kind == "enhancement" || result.kind == "new_feature"'
_CEL_IS_FEATURE_DOC = 'result.kind == "feature"'

# Middle nodes whose hard error routes to the failure handler (on_error
# fan-in). Mirrors _FEATURE_ON_ERROR_SOURCES with the dev-flow intake pair
# substituted for intent_classifier.
_ON_ERROR_SOURCES = (
    DEV_INTAKE,
    IDEATION,
    PLANNER,
    DEVELOPMENT,
    SYNTHESIS,
    QA,
    FEEDBACK_ROUTER,
    FEATURE_HANDOFF,
)

# The reused chain's node ids, in declaration order.
_REUSED_NODE_IDS = (
    PLANNER,
    DEVELOPMENT,
    SYNTHESIS,
    QA,
    FEEDBACK_ROUTER,
    FEATURE_HANDOFF,
    FAILURE,
    CLOSE,
)


def _dev_flow_node(node_id: str) -> NodeDefinition:
    """Build a ``dev_flow.<id>`` NodeDefinition (the two new intake nodes)."""
    return NodeDefinition(id=node_id, type=f"dev_flow.{node_id}")


def _dev_loop_node(node_id: str) -> NodeDefinition:
    """Build a ``dev_loop.<id>`` NodeDefinition (a reused node type).

    Mirrors ``dev_loop.definition._node``: dev-flow consumes the FEAT-378
    chain by **type name**, so these nodes resolve from the same engine
    ``NODE_REGISTRY`` entries the ops flow uses.
    """
    return NodeDefinition(id=node_id, type=f"dev_loop.{node_id}")


def build_dev_flow_definition() -> FlowDefinition:
    """Return the declarative dev-flow :class:`FlowDefinition`.

    Returns:
        The ``flow="dev-flow"`` definition: 10 nodes (the 2 dev-flow intake
        nodes + the 8 reused ``dev_loop`` nodes) and the edge set of spec §2.
        Deliberately absent: ``bug_intake``, ``research``,
        ``deployment_handoff``, ``revision_handoff`` and
        ``intent_classifier`` — dev-flow front-loads no operations concerns.
    """
    nodes = [
        _dev_flow_node(DEV_INTAKE),
        _dev_flow_node(IDEATION),
        *(_dev_loop_node(node_id) for node_id in _REUSED_NODE_IDS),
    ]

    edges = [
        # -- intake fork -------------------------------------------------
        EdgeDefinition(
            **{"from": DEV_INTAKE}, to=IDEATION,
            condition="on_condition", predicate=_CEL_IS_NL_REQUEST,
        ),
        EdgeDefinition(
            **{"from": DEV_INTAKE}, to=PLANNER,
            condition="on_condition", predicate=_CEL_IS_FEATURE_DOC,
        ),
        # IdeationNode returns the FeatureBrief it just produced, so the
        # merge into planner needs no predicate — the OR-join is what makes
        # explicit-edge execution mandatory.
        EdgeDefinition(**{"from": IDEATION}, to=PLANNER, condition="on_success"),
        # -- reused FEAT-378 chain (verbatim) ----------------------------
        EdgeDefinition(**{"from": PLANNER}, to=DEVELOPMENT, condition="on_success"),
        EdgeDefinition(**{"from": DEVELOPMENT}, to=SYNTHESIS, condition="on_success"),
        EdgeDefinition(**{"from": SYNTHESIS}, to=QA, condition="on_success"),
        EdgeDefinition(
            **{"from": QA}, to=FEATURE_HANDOFF,
            condition="on_condition", predicate=_CEL_QA_PASSED,
        ),
        EdgeDefinition(
            **{"from": QA}, to=FEEDBACK_ROUTER,
            condition="on_condition", predicate=_CEL_QA_FAILED,
        ),
        EdgeDefinition(
            **{"from": FEEDBACK_ROUTER}, to=FAILURE,
            condition="on_condition", predicate=_CEL_FEEDBACK_ESCALATE,
        ),
        EdgeDefinition(
            **{"from": FEEDBACK_ROUTER}, to=FEATURE_HANDOFF,
            condition="on_condition", predicate=_CEL_FEEDBACK_ACCEPT,
        ),
        # Bounded repair loop back-edge (FEAT-377/A). A genuine cycle,
        # tolerated by FlowDefinition._validate_acyclic's on_condition
        # exemption; the bound lives in FeedbackRouterNode._retry_allowed().
        EdgeDefinition(
            **{"from": FEEDBACK_ROUTER}, to=DEVELOPMENT,
            condition="on_condition", predicate=_CEL_FEEDBACK_RETRY,
        ),
        EdgeDefinition(**{"from": FEATURE_HANDOFF}, to=CLOSE, condition="on_success"),
    ]
    edges.extend(
        EdgeDefinition(**{"from": src}, to=FAILURE, condition="on_error")
        for src in _ON_ERROR_SOURCES
    )

    return FlowDefinition(
        flow="dev-flow",
        description=(
            "Declarative dev-flow topology (FEAT-412): natural-language or "
            "document intake -> ideation with HITL Open Questions -> the "
            "reused FEAT-378 planning/development/QA chain -> draft PR."
        ),
        nodes=nodes,
        edges=edges,
    )


__all__ = ["build_dev_flow_definition"]
