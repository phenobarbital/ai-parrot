from datetime import datetime, timezone

import pytest

from navrules import (
    AbstractRule,
    ConditionRule,
    EvalContext,
    Environment,
    Policy,
    RuleResult,
    RuleSet,
)

SATURDAY = datetime(2026, 7, 25, 14, 30, tzinfo=timezone.utc)
MONDAY = datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc)


def payrate_rules() -> list[ConditionRule]:
    return [
        ConditionRule(
            name="ot_weekend",
            priority=100,
            conditions={"env.is_weekend": True, "ctx.worked_hours": {"gt": 8}},
            result={"payrate": 33.75, "code": "OT-WKND"},
        ),
        ConditionRule(
            name="weekend",
            priority=90,
            conditions={"env.is_weekend": True},
            result={"payrate": 30.0, "code": "WKND"},
        ),
        ConditionRule(
            name="night",
            priority=50,
            conditions={"env.day_period": {"in": ["evening", "night"]}},
            result={"payrate": 29.5, "code": "NIGHT"},
        ),
    ]


def make_ctx(**kwargs) -> EvalContext:
    return EvalContext.from_user(
        {"email": "e@x.co", "job_code": "TECH1"}, **kwargs
    )


class TestFirstMatch:
    def make_set(self) -> RuleSet:
        rs = RuleSet(
            payrate_rules(),
            policy=Policy.FIRST_MATCH,
            default={"payrate": 25.0, "code": "BASE"},
        )
        rs.compile()
        return rs

    def test_priority_order_and_shortcircuit(self):
        rs = self.make_set()
        res = rs.evaluate_sync(make_ctx(worked_hours=9), Environment(timestamp=SATURDAY))
        assert res.matched is True
        assert res.value["code"] == "OT-WKND"
        assert res.rule.name == "ot_weekend"

    def test_second_rule_wins_when_first_fails(self):
        rs = self.make_set()
        res = rs.evaluate_sync(make_ctx(worked_hours=6), Environment(timestamp=SATURDAY))
        assert res.value["code"] == "WKND"

    def test_default_when_nothing_matches(self):
        rs = self.make_set()
        res = rs.evaluate_sync(make_ctx(worked_hours=6), Environment(timestamp=MONDAY))
        assert res.matched is False
        assert res.value["code"] == "BASE"

    async def test_async_first_match_same_semantics(self):
        rs = self.make_set()
        res = await rs.evaluate(make_ctx(worked_hours=9), Environment(timestamp=SATURDAY))
        assert res.value["code"] == "OT-WKND"
        # short-circuit: only the winner inspected
        assert len(res.results) == 1

    def test_priority_stable_order(self):
        # Two rules with equal priority: insertion order preserved
        rules = [
            ConditionRule(name="a", priority=10, conditions={}, result="A"),
            ConditionRule(name="b", priority=10, conditions={}, result="B"),
        ]
        rs = RuleSet(rules, policy=Policy.FIRST_MATCH)
        rs.compile()
        res = rs.evaluate_sync(make_ctx(), Environment(timestamp=MONDAY))
        assert res.value == "A"

    def test_batch(self):
        rs = self.make_set()
        contexts = [make_ctx(worked_hours=h) for h in (9, 6, 2)]
        results = rs.evaluate_batch(contexts, Environment(timestamp=SATURDAY))
        assert [r.value["code"] for r in results] == ["OT-WKND", "WKND", "WKND"]


class SlowIORule(AbstractRule):
    """Non-declarative rule for mixed-set tests."""

    def __init__(self, outcome=True, **kwargs):
        super().__init__(**kwargs)
        self.outcome = outcome

    def fits(self, ctx, env) -> bool:
        return True

    async def evaluate(self, ctx, env) -> bool:
        return self.outcome


class RaisingRule(AbstractRule):
    def fits(self, ctx, env) -> bool:
        return True

    async def evaluate(self, ctx, env) -> bool:
        raise RuntimeError("boom")


class TestPolicies:
    async def test_all_match(self):
        rs = RuleSet(
            [SlowIORule(True), SlowIORule(True)], policy=Policy.ALL_MATCH
        )
        res = await rs.evaluate(make_ctx(), Environment(timestamp=MONDAY))
        assert res.matched is True

    async def test_all_match_fails_on_one(self):
        rs = RuleSet(
            [SlowIORule(True), SlowIORule(False)], policy=Policy.ALL_MATCH
        )
        res = await rs.evaluate(make_ctx(), Environment(timestamp=MONDAY))
        assert res.matched is False

    async def test_any_match(self):
        rs = RuleSet(
            [SlowIORule(False), SlowIORule(True)], policy=Policy.ANY_MATCH
        )
        res = await rs.evaluate(make_ctx(), Environment(timestamp=MONDAY))
        assert res.matched is True

    async def test_raising_rule_is_no_match_with_error(self):
        rs = RuleSet([RaisingRule()], policy=Policy.ALL_MATCH)
        res = await rs.evaluate(make_ctx(), Environment(timestamp=MONDAY))
        assert res.matched is False
        assert "boom" in res.results[0].error

    async def test_empty_set_all_matches_any_does_not(self):
        env = Environment(timestamp=MONDAY)
        assert (await RuleSet([], policy=Policy.ALL_MATCH).evaluate(make_ctx(), env)).matched
        assert not (await RuleSet([], policy=Policy.ANY_MATCH).evaluate(make_ctx(), env)).matched

    async def test_mixed_first_match_with_io_rule(self):
        rules = [
            SlowIORule(False, name="io_high", priority=100, result="IO"),
            ConditionRule(
                name="fallback", priority=10, conditions={}, result="COND"
            ),
        ]
        rs = RuleSet(rules, policy=Policy.FIRST_MATCH)
        res = await rs.evaluate(make_ctx(), Environment(timestamp=MONDAY))
        assert res.value == "COND"
        assert len(res.results) == 2  # walked both


class TestGuards:
    def test_evaluate_sync_rejects_mixed_sets(self):
        rs = RuleSet([SlowIORule()], policy=Policy.FIRST_MATCH)
        with pytest.raises(RuntimeError, match="declarative"):
            rs.evaluate_sync(make_ctx(), Environment(timestamp=MONDAY))

    def test_rust_backend_unavailable_raises(self):
        rs = RuleSet(
            payrate_rules(), policy=Policy.FIRST_MATCH, backend="rust"
        )
        from navrules import HAS_RUST

        if not HAS_RUST:
            with pytest.raises(RuntimeError, match="native extension"):
                rs.compile()

    def test_fits_all_is_and_of_all_rules(self):
        # Regression for rewards bug (a): one failing rule among passing
        # ones must fail the whole set.
        rules = [
            ConditionRule(name="pass1", conditions={}),
            ConditionRule(name="fail", conditions={"ctx.nope": "x"}),
            ConditionRule(name="pass2", conditions={}),
        ]
        rs = RuleSet(rules)
        assert rs.fits_all(make_ctx(), Environment(timestamp=MONDAY)) is False


class TestRuleResultNormalization:
    async def test_custom_ruleresult_passthrough(self):
        class RichRule(AbstractRule):
            def fits(self, ctx, env):
                return True

            async def evaluate(self, ctx, env):
                return RuleResult(matched=True, rule=self, value={"custom": 1})

        rs = RuleSet([RichRule()], policy=Policy.FIRST_MATCH)
        res = await rs.evaluate(make_ctx(), Environment(timestamp=MONDAY))
        assert res.value == {"custom": 1}

    async def test_true_normalized_to_rule_result_payload(self):
        rule = SlowIORule(True, result={"payrate": 10})
        rs = RuleSet([rule], policy=Policy.FIRST_MATCH)
        res = await rs.evaluate(make_ctx(), Environment(timestamp=MONDAY))
        assert res.value == {"payrate": 10}
