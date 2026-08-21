# TASK-2314: `resolve_rule_references` must walk conditions INSIDE groups

**Feature**: store-context-conditions (FEAT-440) · **Spec**: §3 Module 3
**Status**: done · **Effort**: S · **Depends on**: TASK-2313

## Why

`_eval_condition` reads a field condition's answer through `field_uid`. A
condition left unresolved keeps `field_uid=None`, so the read returns
`None` and the condition never matches — silently.

That is exactly the defect class that made every imported networkninja rule
inert (`mem-bcb5469d8eb0`), and adding a nesting level reintroduces it
unless resolution follows the nesting. It is not hypothetical here: the
first end-to-end run of TASK-2313 returned `False` for all four cases for
precisely this reason.

## What

`core/resolution.py` — an inner `_resolve_rule(rule, owner)` that walks
`rule.conditions` AND every `group.conditions`, applied to both field rules
and section rules.

Context conditions (`source="visit_context"` / `"location_variable"`) carry
no field reference and are skipped, as they already are in the flat path.

## Acceptance

Spec AC6. Three tests in `tests/unit/core/test_resolution.py`: a grouped
field condition gets its `field_uid`; the same for a section rule; a grouped
context condition resolves without raising and keeps `field_uid=None`.
