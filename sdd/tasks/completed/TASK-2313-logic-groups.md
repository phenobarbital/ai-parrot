# TASK-2313: `LogicGroup` — one rule, two independent axes

**Feature**: store-context-conditions (FEAT-440) · **Spec**: §3 Module 2
**Status**: done · **Effort**: M · **Depends on**: —

## Why

`DependencyRule` carries a flat `conditions` list under one `logic` gate, so
the real shape of the `Compliance Images` block — *the store is in one of
these 8 groups AND the visit is one of these 5 types* — cannot be written:
`and` demands all thirteen conditions hold, `or` settles for any one.

The frontend has evaluated `groups` since before the server could express
them (`navigator-svelte src/lib/formbuilder/types/schema.ts`), so this is
aligning the server with a contract that already exists, not inventing one.

## What

`core/constraints.py` — `LogicGroup` (`conditions: list[FieldCondition]`,
`extra="forbid"`) and `DependencyRule.groups: list[LogicGroup] | None`.
Export `LogicGroup` from `core/__init__`.

`services/rule_evaluator.py` — `_eval_rule(rule, …)`: when `rule.groups` is
non-empty, OR the groups and AND within each; otherwise fall back to the
flat `conditions`/`logic` pair. Collapse the three
`_eval_logic(rule.conditions, rule.logic, …)` call sites into it.

## Notes

`_eval_rule` must be the ONE place a `DependencyRule` is evaluated, so field
rules, section rules and post-dependencies inherit groups together rather
than in whichever call site remembered.

An empty `groups` list falls back to the flat pair — the same reading
`_eval_logic` gives an empty condition list, not "nothing can satisfy this".

## Acceptance

Spec AC1, AC4, AC5, AC7. Seven tests in
`test_rule_evaluator.py::TestLogicGroups`, including a rule whose flat list
would say otherwise, and a section rule.
