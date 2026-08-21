# TASK-2315: the networkninja importer emits store-group conditions

**Feature**: store-context-conditions (FEAT-440) · **Spec**: §3 Module 4
**Status**: pending · **Effort**: M · **Depends on**: TASK-2312, TASK-2313

## Why

`NetworkninjaFormService` reads structure from `forms.question_blocks`,
where the store-group condition **does not appear**. Measured 2026-08-21:
all 15 blocks with `block_logic_groups` condition on question 566 (visit
type); none reference a store group, and the 11 group names appear nowhere
in the replicated database. The gating lives only in the Recap Definition
export (`Recap_10.xlsx`), which is not a source this importer reads.

## What

Define and implement the mapping from a per-element list of store-group
names to a rule:

```python
LogicGroup(conditions=[
    FieldCondition(source="visit_context", key="store_groups",
                   operator="contains", value=<group name>)
    for <group name> in groups            # OR'd → one group each
])
```

Groups on an element are alternatives (any one of them shows it), so each
becomes its OWN `LogicGroup`; an existing visit-type condition joins EVERY
group, since it must hold as well.

Wire it wherever that list becomes available. Until the source supplies it,
the mapping is exercised by fixtures only.

## Hazard — do not emit against a live form before fieldsync lands

Nothing populates `visit_context` yet. A correct store-gated rule with no
context fails closed, which is STRICTER than no rule at all: the affected
blocks would vanish for every rep. Emission must not reach a live import
before the fieldsync half supplies the context.

## Acceptance

Fixture-driven: a source element carrying two store groups and a visit-type
condition produces two `LogicGroup`s, each holding one group condition plus
the shared visit-type condition, and evaluates correctly for both groups.
