"""The vocabulary a coupon eligibility rule may speak, in one place.

A rule is written by a tenant, so the set of things it can ask about is a
published contract rather than an implementation detail. :data:`ELIGIBILITY_FIELDS`
*is* that contract: it documents the vocabulary, and the rules API validates
against it, so a typo is refused at write time instead of becoming a rule that
silently never matches.

**Every field is a scalar with a default, never ``None``.** That is not tidiness.
``EvalContext.flatten()`` runs each value through ``_as_scalar``, which returns
``None`` for anything it cannot flatten — and ``flatten`` then drops the key
entirely. A field left as ``None`` therefore *disappears* from the context, and
every condition mentioning it stops matching without a word. Defaults keep the
vocabulary total.

**Counters are precomputed, never queried by a rule.** ``ctx.coupons_issued_90d``
and friends arrive already computed in the flow's shared state. That is what
keeps every rule a declarative ``ConditionRule``, which in turn is what keeps
``RuleSet.evaluate_sync()`` legal and the native backend usable.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from navconfig.logging import logging
from navrules.context import EvalContext
from navrules.environment import Environment

logger = logging.getLogger("parrot_saas.rules.context")

#: Sentinel for "this guest has never had a coupon".
#:
#: Ten years rather than ``None`` so that ``{"gte": 30}`` reads the way a person
#: means it — "not recently, or never" — instead of forcing every rule to spell
#: out an ``is_null`` branch beside every recency test.
NEVER_COUPONED_DAYS = 3650

#: The fields a rule may read, with their defaults and a one-line rationale.
#: Ordered by what a tenant is likeliest to reach for first.
ELIGIBILITY_FIELDS: dict[str, tuple[Any, str]] = {
    # The review itself
    "rating": (0, "star rating, 0 when the source has none"),
    "sentiment": ("neutral", "positive | neutral | mixed | negative"),
    "severity": ("normal", "low | normal | high | critical"),
    "language": ("en", "language of the review"),
    "source": ("", "adapter the review arrived through"),
    "location_ref": ("", "the source's venue identifier"),
    # Did the public reply actually go out?
    "reply_published": (
        False,
        "whether the public reply reached the platform",
    ),
    # Can we lawfully reach this guest?
    "consent_marketing": (False, "guest agreed to be contacted with offers"),
    "has_contact": (False, "an e-mail or phone is on file"),
    "contact_channel": ("none", "none | email | sms | whatsapp"),
    # Who is this guest?
    "lifetime_visits": (0, "visits recorded by the tenant's own systems"),
    # Anti-abuse counters, precomputed by the flow
    "coupons_issued_90d": (0, "coupons issued to this guest in 90 days"),
    "last_coupon_days_ago": (
        NEVER_COUPONED_DAYS,
        f"days since the last coupon; {NEVER_COUPONED_DAYS} means never",
    ),
}


def build_eval_context(shared: Mapping[str, Any]) -> EvalContext:
    """Build the navrules context for one eligibility decision.

    Reads the flow's shared state, filling anything absent from
    :data:`ELIGIBILITY_FIELDS`. Values are coerced to the default's type so a
    stray string rating cannot make every numeric comparison fail quietly.

    Args:
        shared: The flow's per-run shared state. Values may sit at the top
            level (``shared["rating"]``) or under ``shared["eligibility_ctx"]``,
            which is where the coupon nodes put the counters they compute.

    Returns:
        An :class:`EvalContext` whose ``flatten()`` yields ``ctx.<field>`` for
        every name in the vocabulary.
    """
    supplied: dict[str, Any] = {}
    supplied.update(shared.get("eligibility_ctx") or {})

    values: dict[str, Any] = {}
    for field, (default, _) in ELIGIBILITY_FIELDS.items():
        raw = supplied.get(field, shared.get(field, default))
        values[field] = _coerce(field, raw, default)
    return EvalContext(**values)


def _coerce(field: str, value: Any, default: Any) -> Any:
    """Force a supplied value into the field's declared shape.

    A ``None`` becomes the default — see the module docstring for why a ``None``
    in the context is worse than a wrong-but-present value.

    Args:
        field: Field name, used only in the warning.
        value: Whatever the caller supplied.
        default: The declared default, whose type is the target.

    Returns:
        The coerced value, or the default when coercion is impossible.
    """
    if value is None:
        return default
    try:
        if isinstance(default, bool):
            return bool(value)
        if isinstance(default, int):
            return int(value)
        if isinstance(default, str):
            return str(getattr(value, "value", value))
    except (TypeError, ValueError):
        logger.warning(
            "eligibility field %r received %r, which is not a %s; using %r",
            field,
            value,
            type(default).__name__,
            default,
        )
        return default
    return value


def build_environment(shared: Mapping[str, Any]) -> Environment:
    """Build the temporal environment for one eligibility decision.

    Evaluated in the **tenant's** timezone, which is what makes
    ``env.is_weekend``, ``env.day_period`` and ``env.is_month_end`` mean what a
    hospitality business means by them. In UTC, Saturday 23:00 in Madrid is
    already Sunday — a "weekend evening" rule written by the venue would not
    fire on its busiest hour.

    Args:
        shared: The flow's shared state. ``timezone`` names the IANA zone;
            ``now`` may pin the instant (tests, replays).

    Returns:
        A computed :class:`Environment`.
    """
    now = shared.get("now")
    if not isinstance(now, datetime):
        now = datetime.now(timezone.utc)

    tz = None
    name = shared.get("timezone") or "UTC"
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(str(name))
    except Exception as exc:  # noqa: BLE001 - a bad zone must not stop a run
        logger.warning(
            "unknown timezone %r (%s); evaluating rules in UTC", name, exc
        )
        tz = timezone.utc
    return Environment.at(now, tz=tz)


def describe_vocabulary() -> list[dict[str, Any]]:
    """Render the vocabulary for the API, so a client need not hard-code it.

    Returns:
        One entry per field with its default and description.
    """
    return [
        {"field": f"ctx.{name}", "default": default, "description": note}
        for name, (default, note) in ELIGIBILITY_FIELDS.items()
    ]


__all__ = (
    "ELIGIBILITY_FIELDS",
    "NEVER_COUPONED_DAYS",
    "build_environment",
    "build_eval_context",
    "describe_vocabulary",
)
