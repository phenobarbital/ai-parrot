"""Declarative dev-loop topology — ``FlowDefinition`` authoring (FEAT-250 G1).

This module expresses the dev-loop graph declaratively as a
:class:`FlowDefinition` (nodes + edges), replacing the imperative wiring that
used to live inline in :func:`parrot.flows.dev_loop.flow.build_dev_loop_flow`.
The node types are the ``dev_loop.*`` types registered via ``@register_node``
on each node class; the live dependencies are injected at materialization time
by :func:`parrot.flows.dev_loop.factories.build_dev_loop_node_factories`.

Routing predicates are expressed as CEL strings on ``on_condition`` edges.
``cel_evaluator`` coerces a Pydantic node result via ``model_dump()``, so
``result.kind`` (``WorkBrief``) and ``result.passed`` (``QAReport``) resolve
exactly as the legacy Python callables (``_is_bug`` / ``_qa_passed`` …) did.

> **Execution note (engine limitation).** The graph below merges the bug and
> non-bug paths at ``research`` — an **OR-join**. The engine's
> ``from_definition`` scheduler uses an AND-join (a node spawns only when *all*
> its predecessors completed), which cannot fire ``research`` when the
> ``bug_intake`` branch is skipped. The dev-loop therefore *executes* in the
> engine's explicit-edge mode (OR-join + skip-propagation) — see
> ``flow.build_dev_loop_flow``. This module remains the single declarative
> source of the topology (used for materialization, validation, the parity
> test, and visualization).
"""

from __future__ import annotations

from parrot.bots.flows.flow.definition import (
    EdgeDefinition,
    FlowDefinition,
    NodeDefinition,
)


# Node ids == node types' short names (also the constructed nodes' ``node_id``).
INTENT = "intent_classifier"
BUG_INTAKE = "bug_intake"
RESEARCH = "research"
DEVELOPMENT = "development"
QA = "qa"
HANDOFF = "deployment_handoff"
FAILURE = "failure_handler"
CLOSE = "close"
REVISION_HANDOFF = "revision_handoff"

# CEL routing predicates (mirror the legacy Python callables exactly).
_CEL_IS_BUG = 'result.kind == "bug"'
_CEL_IS_NOT_BUG = 'result.kind != "bug"'
_CEL_QA_PASSED = "result.passed == true"
_CEL_QA_FAILED = "result.passed == false"

# Middle nodes whose hard error routes to the failure handler (on_error fan-in).
_ON_ERROR_SOURCES = (INTENT, BUG_INTAKE, RESEARCH, DEVELOPMENT, QA, HANDOFF)


def _node(node_id: str) -> NodeDefinition:
    """Build a ``dev_loop.<id>`` NodeDefinition for ``node_id``."""
    return NodeDefinition(id=node_id, type=f"dev_loop.{node_id}")


def build_dev_loop_definition(*, revision: bool = False) -> FlowDefinition:
    """Return the declarative dev-loop :class:`FlowDefinition`.

    Args:
        revision: When ``True``, return the short revision-mode graph (entering
            at ``development`` and ending at the revision handoff/close). The
            revision graph is authored by FEAT-250 TASK-012; this function
            currently raises for ``revision=True`` so the parameter is part of
            the stable signature from TASK-010 onward.

    Returns:
        A validated initial-run ``FlowDefinition`` reproducing the FEAT-132
        routing plus the new terminal ``close`` node.
    """
    if revision:
        return _build_revision_definition()

    nodes = [
        _node(INTENT),
        _node(BUG_INTAKE),
        _node(RESEARCH),
        _node(DEVELOPMENT),
        _node(QA),
        _node(HANDOFF),
        _node(FAILURE),
        _node(CLOSE),
    ]

    edges = [
        # IntentClassifier branches by kind (bug-first, mirroring R7).
        EdgeDefinition(
            **{"from": INTENT}, to=BUG_INTAKE,
            condition="on_condition", predicate=_CEL_IS_BUG,
        ),
        EdgeDefinition(
            **{"from": INTENT}, to=RESEARCH,
            condition="on_condition", predicate=_CEL_IS_NOT_BUG,
        ),
        # Bug path rejoins the linear chain at research (OR-join merge point).
        EdgeDefinition(**{"from": BUG_INTAKE}, to=RESEARCH, condition="on_success"),
        # Linear chain: research → development → qa.
        EdgeDefinition(**{"from": RESEARCH}, to=DEVELOPMENT, condition="on_success"),
        EdgeDefinition(**{"from": DEVELOPMENT}, to=QA, condition="on_success"),
        # QA branch: passed → handoff, failed → failure handler.
        EdgeDefinition(
            **{"from": QA}, to=HANDOFF,
            condition="on_condition", predicate=_CEL_QA_PASSED,
        ),
        EdgeDefinition(
            **{"from": QA}, to=FAILURE,
            condition="on_condition", predicate=_CEL_QA_FAILED,
        ),
        # Success path terminates at the close node.
        EdgeDefinition(**{"from": HANDOFF}, to=CLOSE, condition="on_success"),
    ]

    # Global error route — any hard error from a middle node → failure handler.
    edges.extend(
        EdgeDefinition(**{"from": src}, to=FAILURE, condition="on_error")
        for src in _ON_ERROR_SOURCES
    )

    return FlowDefinition(
        flow="dev-loop",
        description="Declarative dev-loop topology (FEAT-250).",
        nodes=nodes,
        edges=edges,
    )


def _build_revision_definition() -> FlowDefinition:
    """Return the short revision-mode graph (FEAT-250 G6).

    Enters at ``development`` (reusing the existing clone + branch — no
    Intent/BugIntake/Research/clone), re-runs ``qa``, then on pass pushes to the
    existing branch + comments the same PR via ``revision_handoff`` → ``close``;
    on fail → ``failure_handler``. Like the initial graph it executes in the
    engine's explicit-edge mode (the ``failure_handler`` fan-in is an OR-join).
    """
    nodes = [
        _node(DEVELOPMENT),
        _node(QA),
        _node(REVISION_HANDOFF),
        _node(FAILURE),
        _node(CLOSE),
    ]
    edges = [
        EdgeDefinition(**{"from": DEVELOPMENT}, to=QA, condition="on_success"),
        EdgeDefinition(
            **{"from": QA}, to=REVISION_HANDOFF,
            condition="on_condition", predicate=_CEL_QA_PASSED,
        ),
        EdgeDefinition(
            **{"from": QA}, to=FAILURE,
            condition="on_condition", predicate=_CEL_QA_FAILED,
        ),
        EdgeDefinition(**{"from": REVISION_HANDOFF}, to=CLOSE, condition="on_success"),
    ]
    edges.extend(
        EdgeDefinition(**{"from": src}, to=FAILURE, condition="on_error")
        for src in (DEVELOPMENT, QA, REVISION_HANDOFF)
    )
    return FlowDefinition(
        flow="dev-loop-revision",
        description="Declarative dev-loop revision topology (FEAT-250 G6).",
        nodes=nodes,
        edges=edges,
    )


__all__ = ["build_dev_loop_definition"]
