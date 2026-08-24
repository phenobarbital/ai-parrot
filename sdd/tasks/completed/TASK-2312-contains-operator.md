# TASK-2312: `CONTAINS` / `NOT_CONTAINS` — set membership over a condition source

**Feature**: store-context-conditions (FEAT-440) · **Spec**: `sdd/specs/store-context-conditions.spec.md` §3 Module 1
**Status**: done · **Effort**: S · **Depends on**: —

## Why

`ConditionOperator.IN` asks whether the answer is one of several values.
Store-group membership is the mirror image: the context supplies the list
(`["Best Buy", "Epson Test Store", "Ring of Fire"]`) and the rule names the
single entry it needs. No operator expresses that direction, so a rule
cannot ask "is this store in the Ring of Fire group".

## What

`core/constraints.py` — add `CONTAINS = "contains"` and
`NOT_CONTAINS = "not_contains"` to `ConditionOperator`.

`services/rule_evaluator.py` — add `_holds(raw, expected)` and route both
operators through it from `_eval_condition`'s match.

## Semantics that must hold

- A `list` / `tuple` / `set` source matches when it holds the value.
- A **scalar source counts as a one-element collection** — a store in
  exactly one group still matches.
- A **string source is NOT walked character by character**: `"Ring of Fire"`
  must not contain `"Fire"`. This is the trap in using `in` directly and is
  the whole reason for a helper instead of an inline expression.
- A missing source is `False`, never an error. Absent context fails closed.

## Acceptance

Spec AC2, AC3. Six unit tests in
`tests/unit/services/test_rule_evaluator.py::TestContainsOperator`: list
holding it, list without it, scalar, the substring trap, missing context,
and `NOT_CONTAINS` as the exact negation.
