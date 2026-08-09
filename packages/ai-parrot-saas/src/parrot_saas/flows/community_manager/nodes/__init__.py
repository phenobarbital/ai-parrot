"""Community Manager flow nodes.

Importing this package registers every ``cm.*`` node type in the engine's
global ``NODE_REGISTRY``. Registration is idempotent (see
:func:`~parrot_saas.flows.community_manager.nodes.base.register_cm_node`), so
re-importing after a ``sys.modules`` purge is safe.
"""
from .base import CMNode, register_cm_node
from .coupon import (
    CaptureContactNode,
    CouponDeliverNode,
    CouponEligibilityNode,
    CouponIssueNode,
)
from .intake import ReviewIntakeNode
from .reply import (
    GuardrailNode,
    PublishReplyNode,
    ReplyDraftNode,
    TriageNode,
)
from .terminal import CloseNode, FailureNode

__all__ = (
    "CMNode",
    "CaptureContactNode",
    "CloseNode",
    "CouponDeliverNode",
    "CouponEligibilityNode",
    "CouponIssueNode",
    "FailureNode",
    "GuardrailNode",
    "PublishReplyNode",
    "ReplyDraftNode",
    "ReviewIntakeNode",
    "TriageNode",
    "register_cm_node",
)
