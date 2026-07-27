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

from parrot import conf
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

# FEAT-378 feature-mode node ids.
PLANNER = "planner"
SYNTHESIS = "synthesis"
FEEDBACK_ROUTER = "feedback_router"
FEATURE_HANDOFF = "feature_handoff"

# CEL routing predicates (mirror the legacy Python callables exactly).
_CEL_IS_BUG = 'result.kind == "bug"'
_CEL_IS_NOT_BUG = 'result.kind != "bug"'
_CEL_QA_PASSED = "result.passed == true"
_CEL_QA_FAILED = "result.passed == false"

# FEAT-378 feature-mode CEL routing predicates.
_CEL_IS_FEATURE = 'result.kind == "feature"'
_CEL_FEEDBACK_ESCALATE = 'result.decision == "escalate"'
_CEL_FEEDBACK_ACCEPT = 'result.decision == "accept_with_notes"'
# FEAT-377/A: the `feedback_router -> development` retry edge. Unlike the
# bug-mode qa->development retry edge (whose predicate bounds the loop via
# `result.attempt < N`, read off QAReport), this predicate carries NO
# bound of its own — FeedbackDecision has no attempt counter. The bound
# lives entirely in FeedbackRouterNode._retry_allowed()/_enforce(): a
# proposed "retry" is downgraded to "escalate" in Python, before a
# FeedbackDecision is ever returned, once DEV_LOOP_QA_MAX_RETRIES is
# reached — so by the time this predicate reads `result.decision`, it has
# already been bounded.
_CEL_FEEDBACK_RETRY = 'result.decision == "retry"'


def _cel_qa_retry(max_retries: int) -> str:
    """CEL predicate: QA failed but the bounded repair loop (FEAT-377
    TASK-1910 — G1) still has attempts left → redispatch development."""
    return f"result.passed == false && result.attempt < {max_retries}"


def _cel_qa_exhausted(max_retries: int) -> str:
    """CEL predicate: QA failed and the repair loop is exhausted →
    escalate to the failure handler (the stop rule that bounds the
    otherwise-infinite retry cycle)."""
    return f"result.passed == false && result.attempt >= {max_retries}"

# Middle nodes whose hard error routes to the failure handler (on_error fan-in).
_ON_ERROR_SOURCES = (INTENT, BUG_INTAKE, RESEARCH, DEVELOPMENT, QA, HANDOFF)

# FEAT-378 feature-mode middle nodes whose hard error routes to the failure handler.
_FEATURE_ON_ERROR_SOURCES = (
    INTENT, PLANNER, DEVELOPMENT, SYNTHESIS, QA, FEEDBACK_ROUTER, FEATURE_HANDOFF,
)


def _node(node_id: str) -> NodeDefinition:
    """Build a ``dev_loop.<id>`` NodeDefinition for ``node_id``."""
    return NodeDefinition(id=node_id, type=f"dev_loop.{node_id}")


def build_dev_loop_definition(
    *, revision: bool = False, feature: bool = False
) -> FlowDefinition:
    """Return the declarative dev-loop :class:`FlowDefinition`.

    ``revision`` and ``feature`` mirror the same boolean-flag shape
    (FEAT-378 extends FEAT-250's ``revision: bool`` precedent rather than
    introducing a ``mode`` enum) so the two pre-existing topologies (the
    default bug/enhancement/new_feature graph and the revision graph) stay
    byte-identical — this function only gained a new early-return branch,
    nothing in the default/`revision=True` bodies changed.

    Args:
        revision: When ``True``, return the short revision-mode graph (entering
            at ``development`` and ending at the revision handoff/close).
        feature: When ``True``, return the feature-mode graph (FEAT-378):
            entering at ``intent_classifier`` (routed by ``kind=="feature"``)
            through ``planner``/``development``/``synthesis``/``qa``/
            ``feedback_router``/``feature_handoff``. Mutually exclusive with
            ``revision`` — ``revision`` wins if both are ``True``.

    Returns:
        A validated initial-run ``FlowDefinition`` reproducing the FEAT-132
        routing plus the new terminal ``close`` node (default), the
        FEAT-250 revision graph (``revision=True``), or the FEAT-378
        feature-mode graph (``feature=True``).
    """
    if revision:
        return _build_revision_definition()
    if feature:
        return _build_feature_definition()

    max_retries = int(conf.DEV_LOOP_QA_MAX_RETRIES)

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
        # QA branch: passed → handoff; failed → bounded repair retry to
        # development (FEAT-377 TASK-1910 — G1) while attempts remain, else
        # escalate to the failure handler once the repair loop is exhausted.
        EdgeDefinition(
            **{"from": QA}, to=HANDOFF,
            condition="on_condition", predicate=_CEL_QA_PASSED,
        ),
        EdgeDefinition(
            **{"from": QA}, to=DEVELOPMENT,
            condition="on_condition", predicate=_cel_qa_retry(max_retries),
        ),
        EdgeDefinition(
            **{"from": QA}, to=FAILURE,
            condition="on_condition", predicate=_cel_qa_exhausted(max_retries),
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


def _build_feature_definition() -> FlowDefinition:
    """Return the feature-mode graph (FEAT-378 spec §2 Component Diagram).

    .. code-block:: text

        intent_classifier ─(kind=="feature")→ planner → development → synthesis → qa ─(passed)→ feature_handoff → close
                                                              ↑                     │
                                                              └─(retry, bounded)────┤
                                                                                    │
                                                (escalate / accept_with_notes)→ feedback_router
                                                                                    ├─(escalate)→ failure_handler
                                                                                    └─(accept_with_notes)→ feature_handoff

    Like the initial and revision graphs, this executes in the engine's
    explicit-edge mode (OR-join + skip-propagation): ``feature_handoff``
    has two predecessors (``qa`` on pass, ``feedback_router`` on
    ``accept_with_notes``) — an OR-join the ``from_definition`` AND-join
    scheduler cannot fire correctly, mirroring the default graph's
    ``research`` OR-join. This declarative definition remains the
    reference/validation/visualization source; ``build_dev_loop_feature_flow``
    (runner.py) re-declares every edge imperatively for actual execution.

    The ``feedback_router -> development`` retry edge (FEAT-377/A) is a
    genuine cycle — tolerated by the ``on_condition``-edge exemption in
    ``FlowDefinition._validate_acyclic`` and given real re-entry semantics
    by the engine's cyclic-retry support (both TASK-1910, shared with the
    bug-mode ``qa -> development`` back-edge). See
    ``_CEL_FEEDBACK_RETRY``'s comment above for why this predicate carries
    no bound of its own.
    """
    nodes = [
        _node(INTENT),
        _node(PLANNER),
        _node(DEVELOPMENT),
        _node(SYNTHESIS),
        _node(QA),
        _node(FEEDBACK_ROUTER),
        _node(FEATURE_HANDOFF),
        _node(FAILURE),
        _node(CLOSE),
    ]
    edges = [
        EdgeDefinition(
            **{"from": INTENT}, to=PLANNER,
            condition="on_condition", predicate=_CEL_IS_FEATURE,
        ),
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
        EdgeDefinition(
            **{"from": FEEDBACK_ROUTER}, to=DEVELOPMENT,
            condition="on_condition", predicate=_CEL_FEEDBACK_RETRY,
        ),
        EdgeDefinition(**{"from": FEATURE_HANDOFF}, to=CLOSE, condition="on_success"),
    ]
    edges.extend(
        EdgeDefinition(**{"from": src}, to=FAILURE, condition="on_error")
        for src in _FEATURE_ON_ERROR_SOURCES
    )
    return FlowDefinition(
        flow="dev-loop-feature",
        description="Declarative dev-loop feature-mode topology (FEAT-378).",
        nodes=nodes,
        edges=edges,
    )


__all__ = ["build_dev_loop_definition"]
