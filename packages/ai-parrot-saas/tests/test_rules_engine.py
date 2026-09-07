"""The eligibility vocabulary, rule validation and ruleset construction.

No database, no HTTP. This is where the engine's contract is pinned down,
because every surprise it holds is one that would otherwise surface as a rule
that quietly never fires.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from navrules.context import EvalContext
from navrules.policies import Policy

from parrot_saas.rules.builder import (
    DEFAULT_ELIGIBILITY_RULES,
    RuleValidationError,
    build_ruleset,
    validate_rule,
)
from parrot_saas.rules.context import (
    ELIGIBILITY_FIELDS,
    NEVER_COUPONED_DAYS,
    build_environment,
    build_eval_context,
    describe_vocabulary,
)


def _rule(name: str, priority: int, conditions: dict, offer: str) -> dict:
    """Build a rule spec."""
    return {
        "name": name,
        "priority": priority,
        "conditions": conditions,
        "result": {"offer_code": offer, "reason": name},
    }


def _evaluate(ruleset, **ctx):
    """Evaluate a ruleset against a context built from ``ctx``."""
    shared = {"eligibility_ctx": ctx, "timezone": "UTC"}
    return ruleset.evaluate_sync(
        build_eval_context(shared), build_environment(shared)
    )


# ---------------------------------------------------------------------------
# The vocabulary
# ---------------------------------------------------------------------------


def test_every_field_reaches_the_flattened_context() -> None:
    """A field the vocabulary promises must actually be visible to a rule."""
    flat = build_eval_context({}).flatten(build_environment({}))

    for field in ELIGIBILITY_FIELDS:
        assert f"ctx.{field}" in flat


def test_a_none_disappears_from_the_context() -> None:
    """The reason every field has a default, demonstrated.

    ``flatten()`` runs values through ``_as_scalar``, which returns ``None``
    for anything unflattenable — and then drops the key. A field left as
    ``None`` therefore vanishes, and every condition on it stops matching
    without a word. This is the failure the defaults exist to prevent.
    """
    raw = EvalContext(rating=None, sentiment="negative")

    flat = raw.flatten(None)

    assert "ctx.rating" not in flat
    assert "ctx.sentiment" in flat


def test_a_none_supplied_by_a_caller_becomes_the_default() -> None:
    """So the vanishing above cannot happen through our own builder."""
    flat = build_eval_context({"eligibility_ctx": {"rating": None}}).flatten(None)

    assert flat["ctx.rating"] == 0


def test_values_are_coerced_to_the_declared_shape() -> None:
    """A string rating must not silently break every numeric comparison."""
    ctx = build_eval_context({"eligibility_ctx": {"rating": "4", "has_contact": 1}})

    flat = ctx.flatten(None)
    assert flat["ctx.rating"] == 4
    assert flat["ctx.has_contact"] is True


def test_an_uncoercible_value_falls_back_and_warns(caplog) -> None:
    """Better a documented default than an exception mid-review."""
    import logging

    caplog.set_level(logging.WARNING)

    ctx = build_eval_context({"eligibility_ctx": {"rating": "not a number"}})

    assert ctx.flatten(None)["ctx.rating"] == 0
    assert any("eligibility field" in r.getMessage() for r in caplog.records)


def test_never_couponed_is_a_sentinel_not_a_none() -> None:
    """``{"gte": 30}`` must read as "not recently, or never"."""
    flat = build_eval_context({}).flatten(None)

    assert flat["ctx.last_coupon_days_ago"] == NEVER_COUPONED_DAYS
    assert NEVER_COUPONED_DAYS > 365


def test_the_vocabulary_is_publishable() -> None:
    """Shipped with the listing so a client never hard-codes it."""
    described = describe_vocabulary()

    assert {d["field"] for d in described} == {
        f"ctx.{f}" for f in ELIGIBILITY_FIELDS
    }
    assert all(d["description"] for d in described)


# ---------------------------------------------------------------------------
# The environment
# ---------------------------------------------------------------------------


def test_the_environment_uses_the_tenants_timezone() -> None:
    """A weekend evening in Madrid is the venue's busiest hour.

    Evaluated in UTC, Saturday 23:00 in Madrid is already Sunday — a rule the
    venue wrote about Saturday nights would fire on the wrong day.
    """
    saturday_night_madrid = datetime(2026, 5, 2, 21, 30, tzinfo=timezone.utc)

    madrid = build_environment(
        {"now": saturday_night_madrid, "timezone": "Europe/Madrid"}
    )
    utc = build_environment({"now": saturday_night_madrid, "timezone": "UTC"})

    assert madrid.hour == 23
    assert utc.hour == 21
    assert madrid.is_weekend is True


def test_an_unknown_timezone_degrades_to_utc(caplog) -> None:
    """A typo in a tenant's settings must not stop its reviews."""
    import logging

    caplog.set_level(logging.WARNING)

    env = build_environment({"timezone": "Mars/Olympus_Mons"})

    assert env is not None
    assert any("unknown timezone" in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_a_valid_rule_builds() -> None:
    """The happy path, and the shape the API stores."""
    rule = validate_rule(_rule("x", 10, {"ctx.rating": {"lte": 2}}, "A"))

    assert rule.is_declarative
    assert rule.priority == 10


def test_a_non_declarative_type_is_refused() -> None:
    """``evaluate_sync`` raises on a non-declarative set.

    A rule is stored by one request and evaluated by every review afterwards,
    so this has to be caught at write time.
    """
    spec = _rule("x", 0, {"ctx.rating": {"lte": 2}}, "A")
    spec["rule_type"] = "ComputedRule"

    with pytest.raises(RuleValidationError, match="rule_type"):
        validate_rule(spec)


def test_an_unknown_operator_is_refused() -> None:
    """Caught by construction, not by a hand-maintained operator list."""
    with pytest.raises(RuleValidationError):
        validate_rule(_rule("x", 0, {"ctx.rating": {"roughly": 2}}, "A"))


def test_an_unknown_context_field_is_refused() -> None:
    """A typo is a rule that never matches — and a support ticket."""
    with pytest.raises(RuleValidationError, match="unknown context field") as exc:
        validate_rule(_rule("x", 0, {"ctx.ratingg": {"lte": 2}}, "A"))

    assert exc.value.field == "ctx.ratingg"


def test_an_unknown_environment_field_is_refused() -> None:
    """The env surface is read from Environment, not listed by hand."""
    with pytest.raises(RuleValidationError, match="unknown environment field"):
        validate_rule(_rule("x", 0, {"env.is_full_moon": True}, "A"))


def test_a_real_environment_field_is_accepted() -> None:
    """The hospitality vocabulary navrules already provides."""
    rule = validate_rule(_rule("x", 0, {"env.is_weekend": True}, "A"))

    assert rule.is_declarative


def test_a_bare_field_is_refused() -> None:
    """``flatten`` emits bare aliases where ctx silently wins over env.

    A rule whose meaning depends on that precedence is a rule nobody can read,
    so the prefix is required.
    """
    with pytest.raises(RuleValidationError, match="must start with"):
        validate_rule(_rule("x", 0, {"rating": {"lte": 2}}, "A"))


def test_a_rule_with_no_conditions_is_refused() -> None:
    """It would match everything and shadow every rule below it."""
    with pytest.raises(RuleValidationError, match="at least one condition"):
        validate_rule(_rule("x", 0, {}, "A"))


# ---------------------------------------------------------------------------
# Building and evaluating
# ---------------------------------------------------------------------------


def test_the_ruleset_uses_first_match() -> None:
    """The only policy that returns the winning rule's payload.

    ALL/ANY return the set's ``default`` instead, so the offer code would be
    lost — and the native sync path refuses anything else outright.
    """
    ruleset = build_ruleset([_rule("x", 0, {"ctx.rating": {"lte": 2}}, "A")])

    assert ruleset.policy is Policy.FIRST_MATCH


def test_the_highest_priority_match_wins() -> None:
    """Ordering is the tenant's lever for which offer takes precedence."""
    ruleset = build_ruleset(
        [
            _rule("generic", 10, {"ctx.rating": {"lte": 3}}, "SMALL"),
            _rule("severe", 100, {"ctx.rating": {"lte": 1}}, "BIG"),
        ]
    )

    outcome = _evaluate(ruleset, rating=1)

    assert outcome.matched
    assert outcome.value["offer_code"] == "BIG"
    assert outcome.rule.name == "severe"


def test_equal_priorities_resolve_deterministically() -> None:
    """``compile()`` sorts with a *stable* sort.

    Rules of equal priority therefore keep the order they were added in, which
    is why the repository orders by ``rule_id`` as a second key. Same input,
    same winner, every time.
    """
    specs = [
        _rule("first", 50, {"ctx.rating": {"lte": 3}}, "FIRST"),
        _rule("second", 50, {"ctx.rating": {"lte": 3}}, "SECOND"),
    ]

    winners = {
        build_ruleset(specs).evaluate_sync(
            build_eval_context({"eligibility_ctx": {"rating": 2}}),
            build_environment({}),
        ).value["offer_code"]
        for _ in range(5)
    }

    assert winners == {"FIRST"}


def test_no_match_means_no_coupon() -> None:
    """``default=None`` is the "no offer" answer, not an error."""
    ruleset = build_ruleset([_rule("x", 0, {"ctx.rating": {"lte": 1}}, "A")])

    outcome = _evaluate(ruleset, rating=5)

    assert outcome.matched is False
    assert outcome.value is None


def test_an_empty_ruleset_evaluates_to_no_coupon() -> None:
    """A tenant who has written no rules gets no offers, not a crash."""
    outcome = _evaluate(build_ruleset([]), rating=1)

    assert outcome.matched is False


def test_the_ruleset_compiles_to_the_native_backend() -> None:
    """Losing this costs performance silently, so it is asserted.

    One non-builtin operator drops the whole tenant off the Rust path with no
    error — which is why ``validate_rule`` refuses such rules at write time.
    """
    ruleset = build_ruleset(DEFAULT_ELIGIBILITY_RULES)

    assert ruleset.is_rust_compilable


def test_an_unusable_rule_is_skipped_not_fatal(caplog) -> None:
    """A ruleset is loaded while serving a request.

    One bad row must not take the tenant's whole flow down; the good rules
    still evaluate and the bad one is logged.
    """
    import logging

    caplog.set_level(logging.ERROR)

    ruleset = build_ruleset(
        [
            _rule("good", 10, {"ctx.rating": {"lte": 2}}, "A"),
            _rule("bad", 20, {"ctx.nonsense": {"lte": 2}}, "B"),
        ]
    )

    assert len(ruleset) == 1
    assert _evaluate(ruleset, rating=1).value["offer_code"] == "A"
    assert any("skipping unusable rule" in r.getMessage() for r in caplog.records)


def test_the_native_backend_reports_no_trail_on_a_miss() -> None:
    """A real limitation of the native path, pinned here.

    ``_result_from_indices(None, ...)`` returns ``results=()``, so on the Rust
    path a non-match carries no inspected rules — exactly the case where a
    tenant most needs to know which rules were tried. It is why the dry-run
    endpoint asks for the Python backend instead of taking the fast one.
    """
    ruleset = build_ruleset([_rule("x", 0, {"ctx.rating": {"lte": 1}}, "A")])
    assert ruleset.is_rust_compilable

    outcome = _evaluate(ruleset, rating=5)

    assert outcome.matched is False
    assert outcome.results == ()


def test_the_python_backend_reports_the_full_trail() -> None:
    """Which is what makes the dry-run able to explain itself."""
    ruleset = build_ruleset(
        [
            _rule("high", 100, {"ctx.rating": {"lte": 1}}, "A"),
            _rule("low", 10, {"ctx.rating": {"lte": 2}}, "B"),
        ],
        backend="python",
    )

    outcome = _evaluate(ruleset, rating=5)

    assert outcome.matched is False
    assert [(r.rule.name, r.matched) for r in outcome.results] == [
        ("high", False),
        ("low", False),
    ]


def test_first_match_short_circuits_and_the_trail_shows_it() -> None:
    """A lower-priority rule never getting a look in *is* the explanation."""
    ruleset = build_ruleset(
        [
            _rule("high", 100, {"ctx.rating": {"lte": 3}}, "A"),
            _rule("low", 10, {"ctx.rating": {"lte": 3}}, "B"),
        ],
        backend="python",
    )

    outcome = _evaluate(ruleset, rating=1)

    assert [r.rule.name for r in outcome.results] == ["high"]


# ---------------------------------------------------------------------------
# The shipped starting rules
# ---------------------------------------------------------------------------


def test_the_default_rules_recover_a_detractor() -> None:
    """The case the whole feature exists for."""
    ruleset = build_ruleset(DEFAULT_ELIGIBILITY_RULES)

    outcome = _evaluate(
        ruleset,
        rating=1,
        reply_published=True,
        consent_marketing=True,
        has_contact=True,
        coupons_issued_90d=0,
    )

    assert outcome.value["offer_code"] == "RECOVER20"


@pytest.mark.parametrize(
    "missing", ["reply_published", "consent_marketing", "has_contact"]
)
def test_the_default_rules_refuse_without_consent_contact_or_a_reply(
    missing: str,
) -> None:
    """Conservative by construction: each precondition is load-bearing."""
    ctx = {
        "rating": 1,
        "reply_published": True,
        "consent_marketing": True,
        "has_contact": True,
        "coupons_issued_90d": 0,
    }
    ctx[missing] = False

    assert _evaluate(build_ruleset(DEFAULT_ELIGIBILITY_RULES), **ctx).matched is False


def test_the_default_rules_do_not_repeat_a_recent_coupon() -> None:
    """The anti-abuse counter the flow precomputes."""
    outcome = _evaluate(
        build_ruleset(DEFAULT_ELIGIBILITY_RULES),
        rating=1,
        reply_published=True,
        consent_marketing=True,
        has_contact=True,
        coupons_issued_90d=1,
    )

    assert outcome.matched is False


def test_the_default_rules_thank_a_loyal_promoter() -> None:
    """The second shipped rule, and proof priority ordering is exercised."""
    outcome = _evaluate(
        build_ruleset(DEFAULT_ELIGIBILITY_RULES),
        rating=5,
        lifetime_visits=4,
        consent_marketing=True,
        has_contact=True,
    )

    assert outcome.value["offer_code"] == "LOYAL10"
