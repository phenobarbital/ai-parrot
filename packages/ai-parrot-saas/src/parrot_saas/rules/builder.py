"""Turn stored rule rows into a compiled navrules ``RuleSet``, and refuse bad ones.

Two jobs, and the second is the one that matters operationally.

**Building.** ``Policy.FIRST_MATCH`` is not a preference — it is the only policy
whose ``RuleSetResult.value`` carries the winning rule's payload (ALL/ANY return
the set's ``default``), and the only one the native sync and batch paths accept.
The highest-priority matching offer wins; ``default=None`` means "no coupon".

**Refusing.** Rules are written by tenants, and a bad rule does not fail the
request that stored it — it fails the flow for *every review that tenant
receives afterwards*, because ``RuleSet.evaluate_sync()`` raises on a
non-declarative set. So validation happens at write time, and it validates by
**actually constructing the rule**: a hand-maintained list of legal operators
would drift from ``OperatorRegistry.BUILTIN``, whereas construction cannot.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from navconfig.logging import logging
from navrules.abstract import ConditionRule
from navrules.environment import Environment
from navrules.policies import Policy
from navrules.ruleset import RuleSet

from .context import ELIGIBILITY_FIELDS

logger = logging.getLogger("parrot_saas.rules.builder")

#: The only rule family this deployment accepts. Declarative rules are the ones
#: ``evaluate_sync`` allows and the ones the Rust backend can compile.
RULE_TYPE = "ConditionRule"

#: Prefixes a condition field must carry.
FIELD_PREFIXES = ("ctx.", "env.")

#: Default ruleset name. One per tenant today; the column exists so a second
#: vertical flow does not have to migrate the table.
DEFAULT_RULESET = "coupon_eligibility"


class RuleValidationError(ValueError):
    """A rule spec the engine would choke on, caught at write time.

    Attributes:
        field: The offending condition field, when the problem is local to one.
    """

    def __init__(self, message: str, *, field: str = "") -> None:
        self.field = field
        super().__init__(message)


def _known_env_fields() -> frozenset[str]:
    """Return the attribute names an ``Environment`` actually exposes.

    Read from the class rather than listed by hand: navrules owns that surface
    and this must not drift from it.
    """
    probe = Environment.at(__import__("datetime").datetime(2026, 1, 1))
    return frozenset(probe.to_dict())


def validate_conditions(conditions: Mapping[str, Any]) -> None:
    """Check every condition field against the published vocabulary.

    Args:
        conditions: The condition spec.

    Raises:
        RuleValidationError: On an empty spec, a bare (unprefixed) field, or a
            field outside the vocabulary.
    """
    if not conditions:
        raise RuleValidationError(
            "a rule needs at least one condition; a rule that matches "
            "everything would shadow every rule below it"
        )
    env_fields = _known_env_fields()
    for field in conditions:
        if not isinstance(field, str) or not field.startswith(FIELD_PREFIXES):
            # flatten() emits bare aliases too, so an unprefixed name would
            # often work — but ctx silently wins over env on a collision, and
            # a rule whose meaning depends on that is a rule nobody can read.
            raise RuleValidationError(
                f"condition field {field!r} must start with 'ctx.' or 'env.'",
                field=str(field),
            )
        scope, _, name = field.partition(".")
        if scope == "ctx" and name not in ELIGIBILITY_FIELDS:
            raise RuleValidationError(
                f"unknown context field {field!r}; available: "
                f"{sorted('ctx.' + f for f in ELIGIBILITY_FIELDS)}",
                field=field,
            )
        if scope == "env" and name not in env_fields:
            raise RuleValidationError(
                f"unknown environment field {field!r}; available: "
                f"{sorted('env.' + f for f in env_fields)}",
                field=field,
            )


def validate_rule(spec: Mapping[str, Any]) -> ConditionRule:
    """Validate one rule spec by building it.

    Args:
        spec: A rule spec — ``name``, ``priority``, ``conditions``, ``result``
            and optionally ``rule_type``.

    Returns:
        The constructed rule, so a caller that needs it does not build twice.

    Raises:
        RuleValidationError: If the type is not :data:`RULE_TYPE`, a field is
            outside the vocabulary, an operator is unknown, or the resulting
            rule is not declarative.
    """
    rule_type = spec.get("rule_type", RULE_TYPE)
    if rule_type != RULE_TYPE:
        raise RuleValidationError(
            f"rule_type must be {RULE_TYPE!r}; a non-declarative rule makes "
            "evaluate_sync() raise, which would break the flow for every "
            "review this tenant receives"
        )
    conditions = spec.get("conditions") or {}
    if not isinstance(conditions, Mapping):
        raise RuleValidationError("'conditions' must be a JSON object")
    validate_conditions(conditions)

    try:
        rule = ConditionRule(
            dict(conditions),
            name=str(spec.get("name") or "rule"),
            priority=int(spec.get("priority") or 0),
            result=spec.get("result"),
        )
    except RuleValidationError:
        raise
    except Exception as exc:  # noqa: BLE001 - ConditionError and friends
        raise RuleValidationError(str(exc)) from exc

    if not rule.is_declarative:  # pragma: no cover - ConditionRule always is
        raise RuleValidationError("the rule is not declarative")
    if not rule.condition_set.is_rust_compilable:
        # Not fatal to correctness — the Python path still evaluates it — but
        # one such rule silently drops the whole tenant off the native backend,
        # so it is refused rather than absorbed.
        raise RuleValidationError(
            "the rule uses a non-builtin operator, which would drop this "
            "tenant's whole ruleset off the native backend"
        )
    return rule


def build_ruleset(
    specs: Iterable[Mapping[str, Any]], *, backend: str = "auto"
) -> RuleSet:
    """Compile stored rule specs into an evaluable ``RuleSet``.

    Rules that fail validation are logged and skipped rather than raising: a
    ruleset is loaded while serving a request, and one bad row must not take
    the tenant's whole flow down. The eligibility node reads a rule-less set as
    "no coupon", which is the safe answer.

    Args:
        specs: Rule specs, as :class:`PostgresRuleStorage` yields them.
        backend: ``"auto"`` (the default) uses the native matcher when every
            rule qualifies. Pass ``"python"`` when you need the **per-rule
            trail**: the native path reports only the winning index, and on a
            miss it returns no inspected rules at all — so a caller explaining
            *why* nothing matched gets an empty explanation. The dry-run
            endpoint pays that cost deliberately; the flow does not, because it
            only needs the answer.

    Returns:
        A compiled ``RuleSet`` under ``Policy.FIRST_MATCH``.
    """
    rules = []
    for spec in specs:
        try:
            rules.append(validate_rule(spec))
        except RuleValidationError as exc:
            logger.error(
                "skipping unusable rule %r: %s", spec.get("name", "?"), exc
            )
    ruleset: RuleSet = RuleSet(
        rules, policy=Policy.FIRST_MATCH, default=None, backend=backend
    )
    ruleset.compile()
    return ruleset


#: A starting ruleset, seeded for a new tenant and used by the demo.
#:
#: Deliberately conservative: it offers something only to a guest who is
#: unhappy, reachable, consenting, has not just had a coupon, and whose public
#: reply actually went out.
DEFAULT_ELIGIBILITY_RULES: Sequence[dict[str, Any]] = (
    {
        "name": "recover_detractor",
        "priority": 100,
        "description": "Win back an unhappy guest we were able to answer.",
        "conditions": {
            "ctx.rating": {"lte": 2},
            "ctx.reply_published": True,
            "ctx.consent_marketing": True,
            "ctx.has_contact": True,
            "ctx.coupons_issued_90d": {"lt": 1},
        },
        "result": {"offer_code": "RECOVER20", "reason": "detractor_recovery"},
    },
    {
        "name": "thank_loyal_promoter",
        "priority": 50,
        "description": "Thank a returning guest who left a strong review.",
        "conditions": {
            "ctx.rating": {"gte": 5},
            "ctx.lifetime_visits": {"gte": 3},
            "ctx.consent_marketing": True,
            "ctx.has_contact": True,
            "ctx.last_coupon_days_ago": {"gte": 90},
        },
        "result": {"offer_code": "LOYAL10", "reason": "loyal_promoter"},
    },
)


__all__ = (
    "DEFAULT_ELIGIBILITY_RULES",
    "DEFAULT_RULESET",
    "FIELD_PREFIXES",
    "RULE_TYPE",
    "RuleValidationError",
    "build_ruleset",
    "validate_conditions",
    "validate_rule",
)
