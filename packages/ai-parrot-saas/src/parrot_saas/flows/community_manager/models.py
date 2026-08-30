"""Result models returned by Community Manager flow nodes.

Every field a routing predicate reads obeys three rules, and all three are
consequences of how the engine evaluates CEL:

1. **Non-optional, with a default.** ``CELPredicateEvaluator`` coerces
   ``None`` to an empty string, so ``result.x == null`` can never be true and
   an optional field silently routes as ``""``.
2. **Scalar.** Predicates see only ``result``, ``error`` and an empty ``ctx``;
   nested structures make expressions brittle and unexportable in practice.
3. **Enums dumped as values.** Being a ``str`` subclass is *not* enough:
   ``model_dump()`` in Python mode returns the enum member, and ``celpy``
   stringifies that as ``"GuardrailStatus.BLOCKED"``, not ``"blocked"`` — so
   the predicate quietly evaluates false. :class:`CMResult` sets
   ``use_enum_values`` and ``validate_default`` to store the plain value.

Fields that are *not* read by predicates (reasons, violation lists, ids) are
free to be richer — they exist for humans, audit rows and downstream nodes.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


def _utcnow() -> datetime:
    """Return an aware UTC timestamp."""
    return datetime.now(timezone.utc)


class CMResult(BaseModel):
    """Base for every node result, configured for CEL routing.

    ``use_enum_values`` is **required**, not a preference. The engine coerces
    a node result with ``model_dump()``, which in Python mode returns enum
    *members*; ``celpy`` then stringifies one as ``"GuardrailStatus.BLOCKED"``
    rather than ``"blocked"``, so a predicate like ``result.status ==
    "blocked"`` silently evaluates false and the run takes the wrong branch.
    Storing the plain value sidesteps that entirely.

    ``validate_default`` is required alongside it: Pydantic does not validate
    defaults by default, so a field declared ``TriageAction.SKIP`` would keep
    the enum member and reintroduce the same bug on exactly the paths nobody
    sets explicitly.
    """

    model_config = ConfigDict(use_enum_values=True, validate_default=True)


class TriageAction(str, Enum):
    """What triage decided to do with a review."""

    REPLY = "reply"
    SKIP = "skip"


class Sentiment(str, Enum):
    """Coarse sentiment used by coupon eligibility rules."""

    POSITIVE = "positive"
    NEUTRAL = "neutral"
    MIXED = "mixed"
    NEGATIVE = "negative"


class Severity(str, Enum):
    """How urgently a review needs a human's attention."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class GuardrailStatus(str, Enum):
    """Outcome of the brand/policy guardrail.

    ``REVISE`` is a *status on the result*, not an edge-level retry count, so
    the repair loop can be expressed as a CEL predicate. The bound lives in
    the guardrail node itself — the engine does not bound cycles.
    """

    APPROVED = "approved"
    REVISE = "revise"
    BLOCKED = "blocked"


class ContactChannel(str, Enum):
    """How a guest can be reached with an offer."""

    NONE = "none"
    EMAIL = "email"
    SMS = "sms"
    WHATSAPP = "whatsapp"


class ReviewIntake(CMResult):
    """Normalised review admitted into the flow."""

    review_id: str = ""
    tenant_id: str = ""
    source: str = ""
    external_id: str = ""
    location_ref: str = ""
    rating: int = 0
    text: str = ""
    language: str = "en"
    author_name: str = ""
    guest_id: str = ""
    duplicate: bool = False
    created_at: datetime = Field(default_factory=_utcnow)


class ReviewTriage(CMResult):
    """Triage verdict. ``action`` is the routing field."""

    action: TriageAction = TriageAction.SKIP
    sentiment: Sentiment = Sentiment.NEUTRAL
    severity: Severity = Severity.NORMAL
    language: str = "en"
    topics: List[str] = Field(default_factory=list)
    rationale: str = ""


class ReplyDraft(CMResult):
    """A candidate public reply."""

    text: str = ""
    language: str = "en"
    tone: str = ""
    attempt: int = 1


class GuardrailVerdict(CMResult):
    """Brand/policy check over a draft. ``status`` is the routing field."""

    status: GuardrailStatus = GuardrailStatus.BLOCKED
    attempt: int = 1
    reasons: List[str] = Field(default_factory=list)
    text: str = ""


class PublishResult(CMResult):
    """Outcome of publishing a reply to the review source."""

    published: bool = False
    external_reply_id: str = ""
    reason: str = ""


class ContactCapture(CMResult):
    """Whether the guest can be reached. ``contact_available`` routes."""

    contact_available: bool = False
    channel: ContactChannel = ContactChannel.NONE
    guest_id: str = ""
    handle_fingerprint: str = ""


class CouponDecision(CMResult):
    """navrules eligibility outcome. ``eligible`` routes."""

    eligible: bool = False
    offer_code: str = ""
    reason: str = "no_rule_matched"
    rule_name: str = ""


class CouponIssued(CMResult):
    """Issuance outcome. ``issued`` routes.

    An exhausted budget is a decision, not a failure: it sets ``issued`` to
    ``False`` with a reason and lets the flow close normally rather than
    routing to the failure handler.
    """

    issued: bool = False
    coupon_code: str = ""
    offer_code: str = ""
    reason: str = ""
    expires_at: Optional[datetime] = None


class DeliveryResult(CMResult):
    """Outcome of delivering a coupon to the guest."""

    delivered: bool = False
    channel: ContactChannel = ContactChannel.NONE
    reason: str = ""


class RunSummary(CMResult):
    """Terminal summary of a successful run."""

    review_id: str = ""
    outcome: str = ""
    replied: bool = False
    coupon_issued: bool = False
    coupon_code: str = ""


class FailureSummary(CMResult):
    """Terminal summary when a node errored."""

    review_id: str = ""
    failed_node: str = ""
    error: str = ""


# Every result here is registered with the checkpoint serializer, and that is
# load-bearing rather than tidy. An unregistered model degrades to its ``repr``
# on the way into a checkpoint, so a resumed run would evaluate
# ``result.status == "approved"`` against the *string*
# ``"GuardrailVerdict(status='approved', …)"`` — CEL cannot select a field on a
# string, every predicate raises, and the run takes no branch at all. The whole
# routing of this flow depends on these surviving the round trip.
def _register_checkpoint_types() -> None:
    """Make every routing result survive a checkpoint round-trip."""
    try:
        from parrot.bots.flows.core.checkpoint import register_checkpoint_type
    except ImportError:  # pragma: no cover - core without checkpointing
        return
    for model in (
        ReviewIntake,
        ReviewTriage,
        ReplyDraft,
        GuardrailVerdict,
        PublishResult,
        ContactCapture,
        CouponDecision,
        CouponIssued,
        DeliveryResult,
        RunSummary,
        FailureSummary,
    ):
        register_checkpoint_type(model)


_register_checkpoint_types()


__all__ = (
    "CMResult",
    "ContactCapture",
    "ContactChannel",
    "CouponDecision",
    "CouponIssued",
    "DeliveryResult",
    "FailureSummary",
    "GuardrailStatus",
    "GuardrailVerdict",
    "PublishResult",
    "ReplyDraft",
    "ReviewIntake",
    "ReviewTriage",
    "RunSummary",
    "Sentiment",
    "Severity",
    "TriageAction",
)
