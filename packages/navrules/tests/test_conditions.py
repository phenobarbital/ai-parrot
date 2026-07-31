import pytest

from navrules.conditions import ConditionError, ConditionSet, make_resolver
from navrules.context import EvalContext
from navrules.environment import Environment
from navrules.operators import OperatorRegistry

from datetime import datetime, timezone

SATURDAY = datetime(2026, 7, 25, 14, 30, tzinfo=timezone.utc)


class TestParsing:
    def test_scalar_is_eq_shorthand(self):
        cs = ConditionSet.from_dict({"quarter": "Q3"})
        assert len(cs) == 1
        assert cs.conditions[0].op == "eq"

    def test_operator_map(self):
        cs = ConditionSet.from_dict({"ctx.worked_hours": {"gt": 8}})
        cond = cs.conditions[0]
        assert (cond.field, cond.op, cond.operand) == ("ctx.worked_hours", "gt", 8)

    def test_multiple_operators_and_together(self):
        cs = ConditionSet.from_dict({"ctx.h": {"gte": 4, "lt": 12}})
        assert len(cs) == 2

    def test_unknown_operator_raises(self):
        with pytest.raises(ConditionError, match="Unknown operator"):
            ConditionSet.from_dict({"x": {"wat": 1}})

    def test_empty_operator_map_raises(self):
        with pytest.raises(ConditionError, match="Empty operator map"):
            ConditionSet.from_dict({"x": {}})

    def test_empty_spec_matches_everything(self):
        cs = ConditionSet.from_dict(None)
        assert cs.match_flat({}) is True

    def test_to_spec_roundtrip(self):
        spec = {"ctx.a": {"in": [1, 2]}, "b": True}
        cs = ConditionSet.from_dict(spec)
        assert cs.to_spec() == [
            {"field": "ctx.a", "op": "in", "operand": [1, 2]},
            {"field": "b", "op": "eq", "operand": True},
        ]


class TestMatchFlat:
    def test_and_semantics(self):
        cs = ConditionSet.from_dict(
            {"env.is_weekend": True, "ctx.worked_hours": {"gt": 8}}
        )
        assert cs.match_flat(
            {"env.is_weekend": True, "ctx.worked_hours": 9}
        ) is True
        assert cs.match_flat(
            {"env.is_weekend": True, "ctx.worked_hours": 7}
        ) is False

    def test_missing_field_fails(self):
        cs = ConditionSet.from_dict({"ctx.job_code": "TECH1"})
        assert cs.match_flat({}) is False

    def test_is_null_on_missing(self):
        cs = ConditionSet.from_dict({"ctx.terminated_at": {"is_null": True}})
        assert cs.match_flat({}) is True
        assert cs.match_flat({"ctx.terminated_at": "2026-01-01"}) is False


class TestResolver:
    def make(self, **ctx_kwargs):
        ctx = EvalContext(
            user={"job_code": "TECH1", "email": "a@b.c"},
            session={"programs": ["sales"], "worker_type": "hourly"},
            **ctx_kwargs,
        )
        env = Environment(timestamp=SATURDAY)
        return make_resolver(ctx, env)

    def test_prefixed_lookups(self):
        resolve = self.make(worked_hours=9.5)
        assert resolve("ctx.worked_hours") == 9.5
        assert resolve("ctx.job_code") == "TECH1"
        assert resolve("env.is_weekend") is True

    def test_bare_key_ctx_wins_over_env(self):
        # 'hour' exists in env; add a ctx entry shadowing it
        resolve = self.make(hour=99)
        assert resolve("hour") == 99
        assert resolve("env.hour") == 14

    def test_bare_key_falls_back_to_env(self):
        resolve = self.make()
        assert resolve("quarter") == "Q3"

    def test_session_lookup(self):
        resolve = self.make()
        assert resolve("ctx.worker_type") == "hourly"

    def test_env_method_backed_value(self):
        resolve = self.make()
        assert resolve("env.work_intensity") == "low"  # weekend


class TestCustomOperators:
    def test_custom_operator_flagged_not_compilable(self):
        ops = OperatorRegistry()
        ops.register("divisible_by", lambda v, o: v % o == 0)
        cs = ConditionSet.from_dict({"ctx.n": {"divisible_by": 3}}, ops)
        assert cs.match_flat({"ctx.n": 9}) is True
        assert cs.is_rust_compilable is False

    def test_builtin_only_compilable_even_with_registry(self):
        ops = OperatorRegistry()
        ops.register("divisible_by", lambda v, o: v % o == 0)
        cs = ConditionSet.from_dict({"ctx.n": {"gt": 3}}, ops)
        assert cs.is_rust_compilable is True
