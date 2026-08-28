"""Prompts for the two Community Manager nodes that call a model.

Built **per tenant**, not per call. The agent is constructed once for a tenant
by :mod:`parrot_saas.llm.builder`, and amending a tenant already invalidates
its cached runtime — so a change of brand voice takes effect on the next
review with no extra machinery.

The drafting prompt repeats the guardrail's prohibitions even though the
guardrail enforces them independently. That is deliberate rather than
duplicated: the guardrail is the net, not the instruction. A model that is
never told not to promise a refund writes one, gets rejected, and burns a
second call discovering a rule it could have been given for free.
"""
from __future__ import annotations

from typing import Any, Optional, Sequence

#: Fallback description when a tenant has not written a brand voice.
DEFAULT_BRAND_VOICE = (
    "warm, plain-spoken and specific; never corporate, never effusive"
)

_TRIAGE_SYSTEM = """\
You triage guest reviews for {business}, a hospitality business.

For each review decide:
- action: "reply" when a public response would help, "skip" when it would not.
  Reply to anything with substance, positive or negative. Skip only ratings
  with no text and nothing to acknowledge — a missed reply is a visible
  failure, an unnecessary one is not, so lean towards replying.
- sentiment: positive, neutral, mixed or negative.
- severity: low, normal, high or critical. Reserve critical for claims that
  need a manager today — illness, safety, discrimination, or an accusation
  that could become a legal matter.
- language: the review's own language as a short code ("en", "es", ...).
- topics: a few short tags for what the review is about ("wait time",
  "cleanliness", "staff").
- rationale: one sentence on why, for the operator reading this later.

Judge only what the review says. Do not infer facts about the visit that are
not there.\
"""

_REPLY_SYSTEM = """\
You write public replies to guest reviews on behalf of {business}.

Voice: {voice}
Write in {language} unless the review is clearly in another language, in which
case match the review.

Rules, all of them hard:
- Never invent facts about the visit. You know only what the review says.
- Never promise compensation, refunds, free items or anything "on the house".
  You have no authority to spend the business's money.
- Never mention a discount, coupon, voucher or offer. Any goodwill gesture is
  handled privately and separately; announcing one under a public review turns
  it into a standing promise to everyone who complains.
- Never mention being an AI, and never leave a placeholder of any kind.
- Address what the guest actually raised, specifically. A reply that could be
  pasted under any review is worse than none.
- Two to four sentences. Sign off as the venue, not as a person.

Return only the reply text — no preamble, no quotation marks, no formatting.\
"""


def build_triage_prompt(tenant: Any) -> str:
    """Return the triage agent's system prompt for a tenant.

    Args:
        tenant: The tenant context.

    Returns:
        The system prompt.
    """
    return _TRIAGE_SYSTEM.format(business=_business(tenant))


def build_reply_prompt(tenant: Any) -> str:
    """Return the drafting agent's system prompt for a tenant.

    Args:
        tenant: The tenant context.

    Returns:
        The system prompt, carrying the tenant's own brand voice.
    """
    settings = getattr(tenant, "settings", None) or {}
    return _REPLY_SYSTEM.format(
        business=_business(tenant),
        voice=str(settings.get("brand_voice") or DEFAULT_BRAND_VOICE),
        language=getattr(tenant, "locale", "en") or "en",
    )


def render_triage_task(review: Any) -> str:
    """Return the user message asking for a triage decision.

    Args:
        review: The normalised review.

    Returns:
        The rendered task.
    """
    return (
        "Classify this review.\n\n"
        f"Rating: {getattr(review, 'rating', 0)} out of 5\n"
        f"Language: {getattr(review, 'language', 'en')}\n"
        f"Author: {getattr(review, 'author_name', '') or 'anonymous'}\n"
        f"Review:\n{getattr(review, 'text', '') or '(no text)'}"
    )


def render_reply_task(
    review: Any,
    triage: Optional[Any] = None,
    *,
    previous: str = "",
    reasons: Sequence[str] = (),
) -> str:
    """Return the user message asking for a reply draft.

    On a repair round this carries the rejected draft **and the reasons it was
    rejected**. Without them the model receives an identical prompt, writes an
    identical draft, and the loop runs to its budget without ever converging —
    which is what it did before this argument existed.

    Args:
        review: The normalised review.
        triage: The triage verdict, when one was reached.
        previous: The draft that was rejected, if any.
        reasons: Why it was rejected.

    Returns:
        The rendered task.
    """
    parts = [
        "Write a public reply to this review.",
        "",
        f"Rating: {getattr(review, 'rating', 0)} out of 5",
        f"Language: {getattr(review, 'language', 'en')}",
        f"Review:\n{getattr(review, 'text', '') or '(no text)'}",
    ]
    if triage is not None:
        parts.append(
            f"\nSentiment: {_value(getattr(triage, 'sentiment', ''))}; "
            f"severity: {_value(getattr(triage, 'severity', ''))}"
        )
        topics = getattr(triage, "topics", None)
        if topics:
            parts.append(f"Topics raised: {', '.join(topics)}")

    if previous and reasons:
        parts.extend(
            [
                "",
                "Your previous draft was rejected. Rewrite it.",
                f"Previous draft:\n{previous}",
                "It was rejected because:",
                *(f"- {reason}" for reason in reasons),
                "",
                "Fix every one of those. Do not repeat the previous draft.",
            ]
        )
    return "\n".join(parts)


def _business(tenant: Any) -> str:
    """Return the tenant's display name, or a neutral stand-in."""
    return getattr(tenant, "name", "") or "the venue"


def _value(field: Any) -> str:
    """Render an enum-or-string field as its plain value."""
    return str(getattr(field, "value", field) or "")


__all__ = (
    "DEFAULT_BRAND_VOICE",
    "build_reply_prompt",
    "build_triage_prompt",
    "render_reply_task",
    "render_triage_task",
)
