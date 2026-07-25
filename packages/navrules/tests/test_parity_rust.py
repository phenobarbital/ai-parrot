"""Parity suite: the Rust backend must match the pure-Python matcher
bit-for-bit. Runs only when the native extension is built."""
import json
from datetime import datetime, timezone

import pytest

from navrules import (
    HAS_RUST,
    ConditionRule,
    ConditionSet,
    EvalContext,
    Environment,
    Policy,
    RuleSet,
)

pytestmark = pytest.mark.skipif(
    not HAS_RUST, reason="native extension not built"
)

SATURDAY = datetime(2026, 7, 25, 14, 30, tzinfo=timezone.utc)
MONDAY = datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# Operator-level parity: every op × a hostile grid of values
# ---------------------------------------------------------------------------
OPERAND_CASES = [
    ("eq", True),
    ("eq", 8),
    ("eq", 8.0),
    ("eq", "TECH1"),
    ("eq", [1, 2]),
    ("eq", ["a", "b"]),
    ("ne", 8),
    ("ne", "TECH1"),
    ("gt", 8),
    ("gte", 8.0),
    ("lt", "b"),
    ("lte", 8),
    ("in", ["TECH1", "TECH2"]),
    ("in", [8, 9.0]),
    ("in", "not-a-list"),
    ("not_in", ["MGR"]),
    ("contains", "ECH"),
    ("startswith", "TECH"),
    ("endswith", "1"),
    ("regex", r"^TECH\d$"),
    ("regex", r"\d+"),
    ("between", [5, 10]),
    ("between", [5]),
    ("between", ["a", "c"]),
    ("is_null", True),
    ("is_null", False),
]

VALUE_GRID = [
    "<MISSING>",
    True,
    False,
    0,
    1,
    8,
    8.0,
    8.5,
    -3,
    "8",
    "",
    "TECH1",
    "TECH12",
    "b",
    "abc TECH5 xyz",
    [1, 2],
    [1.0, 2.0],
    ["a", "b"],
    [True],
    [],
]


def _native_single_matches(op: str, operand, value) -> bool:
    from navrules import _native

    spec = json.dumps(
        [{"priority": 0, "conditions": [{"field": "f", "op": op, "operand": operand}]}]
    )
    compiled = _native.compile_ruleset(spec)
    flat = {} if value == "<MISSING>" else {"f": value}
    return compiled.evaluate_first_match(flat) == 0


@pytest.mark.parametrize("op,operand", OPERAND_CASES)
def test_operator_parity(op, operand):
    cs = ConditionSet.from_dict({"f": {op: operand}})
    for value in VALUE_GRID:
        flat = {} if value == "<MISSING>" else {"f": value}
        python_result = cs.match_flat(flat)
        rust_result = _native_single_matches(op, operand, value)
        assert python_result == rust_result, (
            f"parity mismatch: op={op!r} operand={operand!r} value={value!r} "
            f"python={python_result} rust={rust_result}"
        )


# ---------------------------------------------------------------------------
# RuleSet-level parity: first_match over realistic payrate rules
# ---------------------------------------------------------------------------
def payrate_ruleset(backend: str) -> RuleSet:
    rules = [
        ConditionRule(
            name="ot_weekend",
            priority=100,
            conditions={"env.is_weekend": True, "ctx.worked_hours": {"gt": 8}},
            result={"code": "OT-WKND"},
        ),
        ConditionRule(
            name="weekend",
            priority=90,
            conditions={"env.is_weekend": True},
            result={"code": "WKND"},
        ),
        ConditionRule(
            name="tech_long_shift",
            priority=80,
            conditions={
                "ctx.job_code": {"in": ["TECH1", "TECH2"]},
                "ctx.worked_hours": {"between": [8, 16]},
            },
            result={"code": "TECH-LONG"},
        ),
        ConditionRule(
            name="never_terminated",
            priority=70,
            conditions={"ctx.terminated_at": {"is_null": True}, "ctx.worked_hours": {"gte": 12}},
            result={"code": "NOTERM-12"},
        ),
        ConditionRule(
            name="q3",
            priority=10,
            conditions={"env.quarter": "Q3", "ctx.badge": {"regex": r"^B-\d+"}},
            result={"code": "Q3-BADGE"},
        ),
    ]
    rs = RuleSet(
        rules,
        policy=Policy.FIRST_MATCH,
        default={"code": "BASE"},
        backend=backend,
    )
    rs.compile()
    return rs


def context_grid() -> list[EvalContext]:
    contexts = []
    for hours in (2, 8, 8.0, 9, 12.5, None):
        for job in ("TECH1", "MGR", None):
            for badge in ("B-123", "nope", None):
                extra = {}
                if hours is not None:
                    extra["worked_hours"] = hours
                if badge is not None:
                    extra["badge"] = badge
                user = {"email": "e@x.co"}
                if job is not None:
                    user["job_code"] = job
                contexts.append(EvalContext.from_user(user, **extra))
    return contexts


@pytest.mark.parametrize("timestamp", [SATURDAY, MONDAY])
def test_ruleset_parity_single(timestamp):
    env = Environment(timestamp=timestamp)
    rs_py = payrate_ruleset("python")
    rs_rust = payrate_ruleset("rust")
    assert rs_rust._use_rust is True
    for i, (ctx_py, ctx_rust) in enumerate(zip(context_grid(), context_grid())):
        res_py = rs_py.evaluate_sync(ctx_py, env)
        res_rust = rs_rust.evaluate_sync(ctx_rust, env)
        assert (res_py.matched, res_py.value) == (
            res_rust.matched,
            res_rust.value,
        ), f"context #{i}: python={res_py.value} rust={res_rust.value}"


@pytest.mark.parametrize("timestamp", [SATURDAY, MONDAY])
def test_ruleset_parity_batch(timestamp):
    env = Environment(timestamp=timestamp)
    rs_py = payrate_ruleset("python")
    rs_rust = payrate_ruleset("rust")
    py_values = [r.value for r in rs_py.evaluate_batch(context_grid(), env)]
    rust_values = [r.value for r in rs_rust.evaluate_batch(context_grid(), env)]
    assert py_values == rust_values


def test_rust_backend_reports_winner_rule():
    env = Environment(timestamp=SATURDAY)
    rs = payrate_ruleset("rust")
    res = rs.evaluate_sync(
        EvalContext.from_user({"email": "e@x.co"}, worked_hours=9), env
    )
    assert res.matched is True
    assert res.value == {"code": "OT-WKND"}
    assert res.rule.name == "ot_weekend"


def test_auto_backend_picks_rust_when_available():
    rs = payrate_ruleset("auto")
    assert rs._use_rust is True
