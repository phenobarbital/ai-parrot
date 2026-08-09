"""Triage, drafting, guardrail and publication of a public reply.

``TriageNode`` and ``ReplyDraftNode`` become LLM-backed in T15; they carry
deterministic fallbacks here so the whole graph is exercisable without an API
key. ``GuardrailNode`` is deterministic by design — its job is to be the part
that does *not* depend on a model's judgement.
"""
from __future__ import annotations

from typing import Any, Optional

from parrot.bots.flows.core import FlowContext
from parrot.bots.flows.core.types import DependencyResults

from ..models import (
    GuardrailStatus,
    GuardrailVerdict,
    PublishResult,
    ReplyDraft,
    ReviewIntake,
    ReviewTriage,
    Sentiment,
    Severity,
    TriageAction,
)
from .base import CMNode, register_cm_node

#: Ratings at or below this are treated as detractors by the fallback triage.
DETRACTOR_MAX_RATING = 2
#: Ratings at or above this are treated as promoters.
PROMOTER_MIN_RATING = 4


@register_cm_node("cm.triage")
class TriageNode(CMNode):
    """Decide whether a review deserves a reply, and characterise it.

    ``action`` is the routing field: ``reply`` proceeds to drafting, ``skip``
    closes the run. The deterministic fallback replies to everything that
    carries text or a non-neutral rating, which is the conservative choice —
    a missed reply is a visible business failure, an unnecessary one is not.

    Attributes:
        agent: Optional configured agent. When absent the node uses the
            rating-based fallback.
    """

    agent: Optional[Any] = None

    async def execute(
        self, ctx: FlowContext, deps: DependencyResults, **kwargs: Any
    ) -> ReviewTriage:
        """Return the triage verdict for the run's review."""
        review = self._review(ctx)
        triage = self._fallback_triage(review)
        self.shared_state(ctx)["triage"] = triage
        return triage

    def _review(self, ctx: FlowContext) -> ReviewIntake:
        """Return the review under consideration."""
        review = self.shared_state(ctx).get("review")
        if not isinstance(review, ReviewIntake):
            raise ValueError("triage ran without a normalised review")
        return review

    @staticmethod
    def _fallback_triage(review: ReviewIntake) -> ReviewTriage:
        """Characterise a review from its rating alone.

        Args:
            review: The normalised review.

        Returns:
            A triage verdict derived without an LLM.
        """
        if review.rating and review.rating <= DETRACTOR_MAX_RATING:
            sentiment, severity = Sentiment.NEGATIVE, Severity.HIGH
        elif review.rating >= PROMOTER_MIN_RATING:
            sentiment, severity = Sentiment.POSITIVE, Severity.LOW
        else:
            sentiment, severity = Sentiment.MIXED, Severity.NORMAL
        actionable = bool(review.text.strip()) or bool(review.rating)
        return ReviewTriage(
            action=TriageAction.REPLY if actionable else TriageAction.SKIP,
            sentiment=sentiment,
            severity=severity,
            language=review.language,
            rationale="rating-based fallback triage",
        )


@register_cm_node("cm.reply_draft")
class ReplyDraftNode(CMNode):
    """Draft a public reply, incorporating guardrail feedback on a re-entry.

    On the repair loop's back-edge this node runs again with the previous
    verdict's reasons available in shared state, and increments the attempt
    counter that :class:`GuardrailNode` bounds.

    Attributes:
        agent: Optional configured agent; absent means the deterministic
            template below.
    """

    agent: Optional[Any] = None

    async def execute(
        self, ctx: FlowContext, deps: DependencyResults, **kwargs: Any
    ) -> ReplyDraft:
        """Return a candidate reply."""
        shared = self.shared_state(ctx)
        review = shared.get("review")
        state = self.node_state(ctx)
        attempt = int(state.get("attempt", 0)) + 1
        state["attempt"] = attempt

        draft = ReplyDraft(
            text=self._fallback_text(review),
            language=getattr(review, "language", "en"),
            tone="apologetic" if getattr(review, "rating", 0) <= 2 else "warm",
            attempt=attempt,
        )
        shared["draft"] = draft
        return draft

    @staticmethod
    def _fallback_text(review: Optional[ReviewIntake]) -> str:
        """Return a safe, generic reply used when no model is configured."""
        if review is not None and review.rating <= DETRACTOR_MAX_RATING:
            return (
                "We are sorry your visit fell short of what we aim for. "
                "Thank you for telling us — we would like to put it right."
            )
        return "Thank you for taking the time to share your experience."


@register_cm_node("cm.guardrail")
class GuardrailNode(CMNode):
    """Gate a draft against brand and policy rules.

    ``status`` routes: ``approved`` publishes, ``revise`` re-enters drafting,
    ``blocked`` closes the run without publishing.

    **The repair loop's bound lives here**, not on the edge. CEL predicates see
    only the source node's result, and the engine does not bound cycles, so
    once ``max_revise_rounds`` is spent this node downgrades ``revise`` to
    ``blocked`` and the loop terminates.

    Attributes:
        max_revise_rounds: Drafting attempts allowed before a failing draft is
            blocked outright.
        banned_phrases: Case-insensitive substrings that block a draft.
        max_length: Longest acceptable reply.
    """

    max_revise_rounds: int = 2
    banned_phrases: tuple[str, ...] = ()
    max_length: int = 1200

    async def execute(
        self, ctx: FlowContext, deps: DependencyResults, **kwargs: Any
    ) -> GuardrailVerdict:
        """Return the guardrail verdict for the current draft."""
        shared = self.shared_state(ctx)
        draft = shared.get("draft")
        if not isinstance(draft, ReplyDraft):
            raise ValueError("guardrail ran without a draft")

        reasons = self._violations(draft)
        if not reasons:
            verdict = GuardrailVerdict(
                status=GuardrailStatus.APPROVED,
                attempt=draft.attempt,
                text=draft.text,
            )
        elif self._revise_allowed(draft.attempt):
            verdict = GuardrailVerdict(
                status=GuardrailStatus.REVISE,
                attempt=draft.attempt,
                reasons=reasons,
            )
        else:
            verdict = GuardrailVerdict(
                status=GuardrailStatus.BLOCKED,
                attempt=draft.attempt,
                reasons=[*reasons, "revision budget exhausted"],
            )
        shared["guardrail"] = verdict
        return verdict

    def _revise_allowed(self, attempt: int) -> bool:
        """Whether another drafting round is permitted.

        Args:
            attempt: The attempt number of the draft just judged.

        Returns:
            ``True`` while attempts remain.
        """
        return attempt < self.max_revise_rounds

    def _violations(self, draft: ReplyDraft) -> list[str]:
        """Return the reasons a draft is unacceptable, empty when it is fine."""
        reasons: list[str] = []
        text = draft.text.strip()
        if not text:
            reasons.append("empty reply")
        if len(text) > self.max_length:
            reasons.append(f"reply exceeds {self.max_length} characters")
        lowered = text.lower()
        reasons.extend(
            f"contains banned phrase: {phrase!r}"
            for phrase in self.banned_phrases
            if phrase.lower() in lowered
        )
        return reasons


@register_cm_node("cm.publish_reply")
class PublishReplyNode(CMNode):
    """Publish the approved reply through the tenant's review source.

    Attributes:
        review_source: Object implementing the ``ReviewSource`` port. Absent
            in the skeleton, which records the reply without publishing.
        timeout: Wall-clock budget for the outbound call.
    """

    review_source: Optional[Any] = None
    timeout: float = 30.0

    async def execute(
        self, ctx: FlowContext, deps: DependencyResults, **kwargs: Any
    ) -> PublishResult:
        """Publish the approved reply and return the outcome."""
        shared = self.shared_state(ctx)
        verdict = shared.get("guardrail")
        review = shared.get("review")
        text = getattr(verdict, "text", "") or getattr(
            shared.get("draft"), "text", ""
        )

        if self.review_source is None:
            result = PublishResult(
                published=False, reason="no review source configured"
            )
        else:
            reply = await self.with_timeout(
                self.review_source.reply(
                    review.tenant_id, review.external_id, text
                ),
                self.timeout,
                "publishing the reply",
            )
            result = PublishResult(
                published=True, external_reply_id=reply.external_reply_id
            )
        shared["publish"] = result
        return result


__all__ = (
    "GuardrailNode",
    "PublishReplyNode",
    "ReplyDraftNode",
    "TriageNode",
)
