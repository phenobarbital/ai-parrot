# navrules

Generic, low-latency **rule evaluation engine** with priority-ordered
first-match, declarative conditions, and an optional **Rust backend** for the
CPU-bound hot path.

Extracted from a production rewards system; designed to be shared by any
consumer that evaluates "subject + environment vs. N rules": rewards/badges,
payrate selection at clock-out, eligibility checks, etc.

- **Zero mandatory dependencies** — stdlib only; `pandas` and `cel` are extras.
- **Two-phase rule contract** — `fits(ctx, env)` (sync, cheap pre-filter) and
  `async evaluate(ctx, env)` (full evaluation, may do I/O).
- **Policies** — `ALL_MATCH`, `ANY_MATCH`, `FIRST_MATCH` (priority-ordered,
  short-circuiting, typed result payload).
- **Rust hot path** — declarative rule sets compile once into a native
  matcher (PyO3 + rayon, GIL released); pure-Python fallback is always
  available (`navrules.HAS_RUST` tells you which one is active).

## Quick start: payrate selection at clock-out

```python
from navrules import ConditionRule, EvalContext, Environment, Policy, RuleSet

ruleset: RuleSet[dict] = RuleSet(
    policy=Policy.FIRST_MATCH,
    default={"payrate": 25.0, "code": "BASE"},
)
ruleset.add_rule({
    "rule_type": "ConditionRule",
    "name": "ot_weekend",
    "priority": 100,
    "conditions": {"env.is_weekend": True, "ctx.worked_hours": {"gt": 8}},
    "result": {"payrate": 33.75, "code": "OT-WKND"},
})
ruleset.add_rule({
    "rule_type": "ConditionRule",
    "name": "night_diff",
    "priority": 90,
    "conditions": {
        "env.day_period": {"in": ["evening", "night"]},
        "ctx.job_code": {"in": ["TECH1", "TECH2"]},
    },
    "result": {"payrate": 29.50, "code": "NIGHT"},
})
ruleset.compile()  # sorts by priority, compiles to Rust when available

# hot path — one call per clock-out, no async, no I/O:
env = Environment.at(clockout_ts, tz=site_tz)
ctx = EvalContext.from_user(employee, worked_hours=9.5, job_code="TECH1")
result = ruleset.evaluate_sync(ctx, env)
payrate = result.value["payrate"]

# end-of-day close, thousands of activities (rayon batch):
results = ruleset.evaluate_batch(contexts, env)
```

## Condition DSL

JSON-friendly dict, one entry per field (entries AND together):

```json
{
    "env.is_weekend": true,
    "ctx.worked_hours": {"gte": 4, "lt": 12},
    "ctx.job_code": {"in": ["TECH1", "TECH2"]},
    "quarter": "Q4"
}
```

- Scalar value ⇒ `eq` shorthand. A `{op: operand}` map applies operators;
  multiple operators under one field AND together.
- `ctx.` prefix reads the evaluation context, `env.` the environment; bare
  keys resolve ctx first, then env.
- Operators: `eq ne gt gte lt lte in not_in contains startswith endswith
  regex between is_null`.
- Missing values match only `is_null`; `bool` never coerces to a number;
  `int`/`float` coerce to each other. The Rust backend mirrors these
  semantics bit-for-bit (enforced by the parity suite).
- Custom operators can be registered on an `OperatorRegistry`; rule sets
  using them transparently fall back to the Python matcher.

## Rule families

| Family | Use case | Backend |
|---|---|---|
| `ConditionRule` | Declarative conditions, CPU-bound (payrates, ambient rules) | Rust or Python |
| `AbstractRule` subclass | Code rules; `evaluate()` may hit a DB or service | Python (async) |
| `ComputedRule` | Pull pattern: the rule queries its own candidates | Python (async) |

Mixed sets work: `await ruleset.evaluate(ctx, env)` walks rules in priority
order, awaiting I/O rules in their turn.

## Environment

`Environment` derives ~35 temporal fields from a single timestamp
(`is_weekend`, `quarter`, `day_period`, `week_position`, `is_pay_period`,
business-day counters...). `Environment.at(ts, tz=...)` evaluates at any
instant and timezone; `extra={...}` carries site-specific ambient values.

## Loading rules from storage

```python
from navrules.storages import FileStorage

async with FileStorage("payrate_rules.json") as storage:
    for spec in await storage.load():
        ruleset.add_rule(spec)
ruleset.compile()
```

`AbstractStorage` is the extension point for DB-backed definitions.

## Development

```bash
# Python-only (fallback backend):
uv run --no-project --with pytest --with pytest-asyncio --with-editable . pytest tests

# Native backend:
make build-rust      # maturin develop --release
cargo test           # crate unit tests (rust/)
RUN_BENCH=1 pytest tests/benchmarks -s
```

The wheel is built with maturin (`abi3-py311`: one wheel covers CPython
3.11+). If the native extension cannot be imported, navrules silently runs
on the pure-Python matcher — set `NAVRULES_DISABLE_RUST=1` to force it.
