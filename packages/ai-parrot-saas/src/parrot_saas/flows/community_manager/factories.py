"""Node factories binding the flow's nodes to one tenant's live dependencies.

``AgentsFlow.from_definition`` accepts a ``node_factories`` mapping keyed by
node *type*; each factory receives the node definition plus its derived
dependency and successor sets, and returns a live :class:`Node`. This is the
extension point for anything that cannot travel inside a
``NodeDefinition.config`` blob — configured agents, repositories, compiled
rulesets, HTTP clients.

It is also where the tenant becomes part of the graph: every factory closes
over the :class:`TenantContext`, so each node instance is tenant-bound at
construction. That is what makes explicit tenant passing workable without a
context variable — the binding happens once, at build time, rather than being
read from ambient state at execution time on a background worker.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Set

from parrot.bots.flows.core.node import Node
from parrot.bots.flows.flow.definition import NodeDefinition

from ...tenancy.context import TenantContext
from . import definition as topo
from .nodes import (
    CaptureContactNode,
    CloseNode,
    CouponDeliverNode,
    CouponEligibilityNode,
    CouponIssueNode,
    FailureNode,
    GuardrailNode,
    PublishReplyNode,
    ReplyDraftNode,
    ReviewIntakeNode,
    TriageNode,
)

NodeFactory = Callable[[NodeDefinition, Set[str], Set[str]], Node]


def build_cm_node_factories(
    *,
    tenant: TenantContext,
    triage_agent: Optional[Any] = None,
    reply_agent: Optional[Any] = None,
    review_source: Optional[Any] = None,
    review_repository: Optional[Any] = None,
    guest_repository: Optional[Any] = None,
    ruleset: Optional[Any] = None,
    issuer: Optional[Any] = None,
    delivery: Optional[Any] = None,
    node_timeout: float = 120.0,
) -> Dict[str, NodeFactory]:
    """Build the ``node_factories`` mapping for one tenant.

    Every dependency is optional so the graph can be built — and its routing
    exercised — with nothing wired in. That is what lets the topology be
    tested without an API key, a database or a review platform.

    Args:
        tenant: The tenant this flow instance serves.
        triage_agent: Configured agent for triage; ``None`` uses the
            rating-based fallback.
        reply_agent: Configured agent for drafting; ``None`` uses a template.
        review_source: Adapter implementing the ``ReviewSource`` port.
        review_repository: Repository the review's status and every reply
            attempt are recorded in.
        guest_repository: Repository resolving guest contact details.
        ruleset: Compiled navrules ``RuleSet`` for coupon eligibility.
        issuer: Coupon issuance service.
        delivery: Coupon delivery service.
        node_timeout: Wall-clock budget applied to each outbound call. The
            scheduler enforces no timeout of its own.

    Returns:
        Mapping of registered node type to factory callable.
    """
    max_revise = int(
        tenant.setting("max_revise_rounds", 2)
    )
    banned = tuple(tenant.setting("banned_phrases", ()) or ())

    def _with(cls, **bound):
        """Return a factory constructing ``cls`` with bound dependencies."""

        def _factory(
            node_def: NodeDefinition, deps: Set[str], succs: Set[str]
        ) -> Node:
            return cls(
                node_id=node_def.id,
                dependencies=deps,
                successors=succs,
                **bound,
            )

        return _factory

    return {
        topo.NODE_TYPES[topo.REVIEW_INTAKE]: _with(
            ReviewIntakeNode,
            review_repository=review_repository,
            tenant_id=tenant.tenant_id,
            timezone=tenant.timezone,
        ),
        topo.NODE_TYPES[topo.TRIAGE]: _with(TriageNode, agent=triage_agent),
        topo.NODE_TYPES[topo.REPLY_DRAFT]: _with(
            ReplyDraftNode, agent=reply_agent
        ),
        topo.NODE_TYPES[topo.GUARDRAIL]: _with(
            GuardrailNode,
            max_revise_rounds=max_revise,
            banned_phrases=banned,
        ),
        topo.NODE_TYPES[topo.PUBLISH_REPLY]: _with(
            PublishReplyNode,
            review_source=review_source,
            review_repository=review_repository,
            timeout=node_timeout,
        ),
        topo.NODE_TYPES[topo.CAPTURE_CONTACT]: _with(
            CaptureContactNode, guest_repository=guest_repository
        ),
        topo.NODE_TYPES[topo.COUPON_ELIGIBILITY]: _with(
            CouponEligibilityNode, ruleset=ruleset
        ),
        topo.NODE_TYPES[topo.COUPON_ISSUE]: _with(
            CouponIssueNode, issuer=issuer
        ),
        topo.NODE_TYPES[topo.COUPON_DELIVER]: _with(
            CouponDeliverNode, delivery=delivery, timeout=node_timeout
        ),
        topo.NODE_TYPES[topo.CLOSE]: _with(
            CloseNode, review_repository=review_repository
        ),
        topo.NODE_TYPES[topo.FAILURE]: _with(
            FailureNode, review_repository=review_repository
        ),
    }


__all__ = ("NodeFactory", "build_cm_node_factories")
