# TASK-2316: accept and propagate the store context through the HTTP surface

**Feature**: store-context-conditions (FEAT-440) · **Spec**: §3 Module 5
**Status**: pending · **Effort**: M · **Depends on**: TASK-2313

## Why

`RuleEvaluator.resolve()` and `FormValidator.validate()` both accept
`visit_context`, and **no caller anywhere populates it** — verified across
the package. The evaluation path is complete and unreachable.

## What

The render and validate handlers accept a caller-supplied store context and
pass it through as `visit_context`. The caller is FieldSync, which knows
which store a visit belongs to; this package only accepts what it is handed
and never resolves a store itself.

## Notes

Absent context means no context: a rule that asks about a store the caller
did not describe does not fire. Failing closed is deliberate — the
alternative reveals store-gated questions to every store.

The contract for the key (`store_groups`) and its value shape (a list of
group names) is shared with the fieldsync half and must be agreed there
before this lands, not invented here.

## Acceptance

An end-to-end request carrying a store context resolves a store-gated rule
correctly; the same request without it leaves the rule unfired.
