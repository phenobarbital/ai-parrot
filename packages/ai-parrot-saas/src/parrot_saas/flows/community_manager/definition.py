"""Declarative topology of the Community Manager flow.

This module is the single source of truth for node ids and routing
predicates. ``flow.py`` re-declares the same edges imperatively — the engine's
``from_definition`` scheduler uses an AND-join, which cannot fire this graph's
OR-joins — and it does so by **importing the constants below**, so the
declarative and executable graphs cannot silently drift.

Every predicate is a **CEL string**. That is a hard constraint, not a style
choice: a Python callable predicate makes ``AgentsFlow.to_definition()`` raise
``FlowNotExportableError``, and with ``checkpoint=True`` the engine calls that
during ``run_flow`` — so one callable disables checkpoint/suspend/resume for
the whole flow, failing before any node executes.

Topology::

    review_intake → triage ─(skip)─────────────────────────────────────┐
                       │                                               │
                    (reply)                                            │
                       ▼                                               │
                  reply_draft ──▶ guardrail ─(blocked)─────────────────┤
                       ▲              │                                │
                       └──(revise)────┤                                │
                                 (approved)                            │
                                      ▼                                │
                              publish_reply → capture_contact          │
                                                   │                   │
                                    (no contact)───┼───────────────────┤
                                                   │                   │
                                             (has contact)             │
                                                   ▼                   │
                                          coupon_eligibility           │
                                             │           │             │
                                     (not eligible)──────┼─────────────┤
                                             │           │             │
                                        (eligible)       │             │
                                             ▼           │             │
                                       coupon_issue ─(not issued)──────┤
                                             │                         │
                                        (issued)                       │
                                             ▼                         │
                                      coupon_deliver ──────────────────┤
                                                                       ▼
                                                                     close

    every middle node ──on_error──▶ failure_handler

``close`` therefore has six predecessors, and the guardrail repair loop is a
cycle — both of which require the engine's explicit-edge mode (OR-join with
skip propagation). ``_validate_acyclic`` permits the cycle because it is an
``on_condition`` edge.

This module is pure: no environment reads, no I/O, no imports from the runtime
layer.
"""
from __future__ import annotations

from parrot.bots.flows.flow.definition import (
    EdgeDefinition,
    FlowDefinition,
    NodeDefinition,
)

# ---------------------------------------------------------------------------
# Node ids
# ---------------------------------------------------------------------------
REVIEW_INTAKE = "review_intake"
TRIAGE = "triage"
REPLY_DRAFT = "reply_draft"
GUARDRAIL = "guardrail"
PUBLISH_REPLY = "publish_reply"
CAPTURE_CONTACT = "capture_contact"
COUPON_ELIGIBILITY = "coupon_eligibility"
COUPON_ISSUE = "coupon_issue"
COUPON_DELIVER = "coupon_deliver"
CLOSE = "close"
FAILURE = "failure_handler"

#: Registered node types. Namespaced ``cm.*`` because ``NODE_REGISTRY`` is
#: process-global and already holds the dev-loop and dev-flow types.
NODE_TYPES = {
    REVIEW_INTAKE: "cm.review_intake",
    TRIAGE: "cm.triage",
    REPLY_DRAFT: "cm.reply_draft",
    GUARDRAIL: "cm.guardrail",
    PUBLISH_REPLY: "cm.publish_reply",
    CAPTURE_CONTACT: "cm.capture_contact",
    COUPON_ELIGIBILITY: "cm.coupon_eligibility",
    COUPON_ISSUE: "cm.coupon_issue",
    COUPON_DELIVER: "cm.coupon_deliver",
    CLOSE: "cm.close",
    FAILURE: "cm.failure",
}

#: Nodes that route to the failure handler when they raise.
MIDDLE_NODES = (
    REVIEW_INTAKE,
    TRIAGE,
    REPLY_DRAFT,
    GUARDRAIL,
    PUBLISH_REPLY,
    CAPTURE_CONTACT,
    COUPON_ELIGIBILITY,
    COUPON_ISSUE,
    COUPON_DELIVER,
)

# ---------------------------------------------------------------------------
# CEL routing predicates
# ---------------------------------------------------------------------------
CEL_TRIAGE_REPLY = 'result.action == "reply"'
CEL_TRIAGE_SKIP = 'result.action == "skip"'
CEL_GUARDRAIL_APPROVED = 'result.status == "approved"'
#: Back-edge into ``reply_draft``. The bound is NOT here — CEL sees only the
#: source node's result, so the stop rule lives in ``GuardrailNode``, which
#: downgrades ``revise`` to ``blocked`` once the attempt budget is spent.
CEL_GUARDRAIL_REVISE = 'result.status == "revise"'
CEL_GUARDRAIL_BLOCKED = 'result.status == "blocked"'
CEL_HAS_CONTACT = "result.contact_available == true"
CEL_NO_CONTACT = "result.contact_available == false"
CEL_COUPON_ELIGIBLE = "result.eligible == true"
CEL_COUPON_NOT_ELIGIBLE = "result.eligible == false"
CEL_COUPON_ISSUED = "result.issued == true"
CEL_COUPON_NOT_ISSUED = "result.issued == false"

#: The executable graph, as ``(source, target, condition, predicate)``.
#: ``flow.py`` iterates this so the two graphs cannot diverge.
EDGES: tuple[tuple[str, str, str, str | None], ...] = (
    (REVIEW_INTAKE, TRIAGE, "on_success", None),
    (TRIAGE, REPLY_DRAFT, "on_condition", CEL_TRIAGE_REPLY),
    (TRIAGE, CLOSE, "on_condition", CEL_TRIAGE_SKIP),
    (REPLY_DRAFT, GUARDRAIL, "on_success", None),
    (GUARDRAIL, PUBLISH_REPLY, "on_condition", CEL_GUARDRAIL_APPROVED),
    (GUARDRAIL, REPLY_DRAFT, "on_condition", CEL_GUARDRAIL_REVISE),
    (GUARDRAIL, CLOSE, "on_condition", CEL_GUARDRAIL_BLOCKED),
    (PUBLISH_REPLY, CAPTURE_CONTACT, "on_success", None),
    (CAPTURE_CONTACT, COUPON_ELIGIBILITY, "on_condition", CEL_HAS_CONTACT),
    (CAPTURE_CONTACT, CLOSE, "on_condition", CEL_NO_CONTACT),
    (COUPON_ELIGIBILITY, COUPON_ISSUE, "on_condition", CEL_COUPON_ELIGIBLE),
    (COUPON_ELIGIBILITY, CLOSE, "on_condition", CEL_COUPON_NOT_ELIGIBLE),
    (COUPON_ISSUE, COUPON_DELIVER, "on_condition", CEL_COUPON_ISSUED),
    (COUPON_ISSUE, CLOSE, "on_condition", CEL_COUPON_NOT_ISSUED),
    (COUPON_DELIVER, CLOSE, "on_success", None),
) + tuple((source, FAILURE, "on_error", None) for source in MIDDLE_NODES)


def build_cm_flow_definition(
    *, name: str = "community-manager", version: str = "1.0"
) -> FlowDefinition:
    """Build the declarative :class:`FlowDefinition` for the flow.

    Used for validation, visualisation and checkpoint export. Execution goes
    through ``build_community_manager_flow`` in ``flow.py``, which re-declares
    the same edges imperatively to get explicit-edge mode.

    Args:
        name: Flow name.
        version: Definition version string.

    Returns:
        A validated :class:`FlowDefinition`.
    """
    nodes = [
        NodeDefinition(id=node_id, type=node_type, label=node_id)
        for node_id, node_type in NODE_TYPES.items()
    ]
    edges = [
        EdgeDefinition(
            **{"from": source},
            to=target,
            condition=condition,
            predicate=predicate,
        )
        for source, target, condition, predicate in EDGES
    ]
    return FlowDefinition(
        flow=name,
        version=version,
        description=(
            "Autonomous community manager: triage a review, draft and publish "
            "a reply, then capture contact and issue a coupon when the "
            "tenant's navrules ruleset says the guest is eligible."
        ),
        nodes=nodes,
        edges=edges,
    )


__all__ = (
    "CAPTURE_CONTACT",
    "CEL_COUPON_ELIGIBLE",
    "CEL_COUPON_ISSUED",
    "CEL_COUPON_NOT_ELIGIBLE",
    "CEL_COUPON_NOT_ISSUED",
    "CEL_GUARDRAIL_APPROVED",
    "CEL_GUARDRAIL_BLOCKED",
    "CEL_GUARDRAIL_REVISE",
    "CEL_HAS_CONTACT",
    "CEL_NO_CONTACT",
    "CEL_TRIAGE_REPLY",
    "CEL_TRIAGE_SKIP",
    "CLOSE",
    "COUPON_DELIVER",
    "COUPON_ELIGIBILITY",
    "COUPON_ISSUE",
    "EDGES",
    "FAILURE",
    "GUARDRAIL",
    "MIDDLE_NODES",
    "NODE_TYPES",
    "PUBLISH_REPLY",
    "REPLY_DRAFT",
    "REVIEW_INTAKE",
    "TRIAGE",
    "build_cm_flow_definition",
)
