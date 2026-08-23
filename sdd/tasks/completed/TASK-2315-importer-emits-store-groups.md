# TASK-2315: the networkninja importer emits store-group conditions

**Feature**: store-context-conditions (FEAT-440) · **Spec**: §3 Module 4
**Status**: done · **Effort**: M · **Depends on**: TASK-2312, TASK-2313

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

### Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-08-24

Added `NetworkninjaFormService._map_store_group_rule()` (static): takes a
list of store-group names plus any conditions already collected for the
element, and returns a `DependencyRule` expressed via `groups` — one
`LogicGroup` per store-group name, each holding a `visit_context` `CONTAINS`
condition for that group plus a fresh copy of every shared condition (so
resolution's per-condition `field_uid` write never aliases the same
instance across groups).

Wired into `_map_logic_groups()` via a new `store_groups` key read
generically off the `question`/block-shim dict (mirrors the existing
`logic_groups`/`question_logic_groups` pattern), and into
`_map_block_to_section()`'s block-level shim via a new `_block_store_groups()`
accessor (mirrors `_block_logic_groups()`). No source row this importer
reads populates `store_groups` today — verified: the SQL query
(`_FORM_QUERY`) selects no such column, and `networkninja.stores` / every
`*group*` table in the replicated DB carries no store-group data (per the
spec's own verification). The wiring is therefore inert against every live
import and activates only via fixtures/tests, per the Hazard note above.

**Found and fixed a real bug the wiring would otherwise hit**:
`_prune_dangling_rule_references()` only ever pruned `rule.conditions` (the
flat list). A groups-only rule sets `conditions=[]` by design (that's not
"everything pruned," it never carried anything), so the old pruning logic
saw `kept=[]` and dropped the ENTIRE store-group rule unconditionally — every
store-gated element would have silently lost its rule on import. Extended
`_prune` to also walk and prune each group's conditions, dropping only a
group left with nothing (not the whole rule), and only returning `None`
when both the flat conditions AND every group end up empty. This is in the
same file already in scope for this task and required for the acceptance
criterion to hold end-to-end, so it was fixed here rather than filed as a
separate follow-up.

**Tests** (`test_networkninja_importer.py`, 5 new, all fixture-driven):
one-`LogicGroup`-per-store-group with the shared condition copied in;
independent-instance guard (no aliasing across groups); store-group-alone
(no shared condition) case; dangling-shared-condition pruning drops only
that condition/group, not the whole rule; and a full `RuleEvaluator`
end-to-end pass across all four combinations of matching/non-matching
store + answer, including the fail-closed "no context at all" case.

**Verification**: `pytest packages/parrot-formdesigner/tests/ -q` — 40
pre-existing failures, byte-identical failing-test set before and after
(diffed explicitly, confirms AC8); 2212 passed (2207 baseline + 5 new).
`ruff check` on both changed files — same 7 pre-existing findings as
baseline (unrelated: import sorting, `noqa` cleanup, `UP017`, one unused
unpack in an untouched test), zero new findings.

**Deviations from spec**: none. `store_groups` as the wiring key name is
this implementation's own choice (no real source column exists to match
against yet — spec explicitly defers "sourcing store-group membership" to
fieldsync); it mirrors the `visit_context` key name (`store_groups`) used
throughout the spec's example and the already-shipped evaluator tests
(TASK-2312/2313), so it is consistent with the rest of the feature rather
than invented in isolation.

---

### Post-completion code-review fix (2026-08-24)

The adversarial `code-reviewer` pass on the full FEAT-440 diff found a
**CRITICAL, reproducible correctness bug** in `_map_store_group_rule`:
every `shared_conditions` entry was ANDed verbatim into each store-group
`LogicGroup`. When the source expresses an answer alternative as TWO
`logic_groups` on the SAME field (e.g. "visit type == Brand Ambassador OR
visit type == Assisted Sales") — which the spec's own Motivation (§1)
names as the MAJORITY real dual-axis shape (23 of 26 elements needing
AND-of-ORs) — this produced `field_9050 == "4784" AND field_9050 ==
"4782"` inside every group: unsatisfiable for a single-valued field, so
the imported rule could never fire for ANY store or answer. The
reviewer reproduced this directly against the worktree code (not just by
reading it) and I independently re-reproduced their exact repro before
fixing.

**Root cause**: the flat (non-store) path already handles this exact case
correctly, by choosing a top-level `logic="or"` when every condition
targets the same field (see the "Multiple groups mean AND — EXCEPT..."
comment above the flat-path return). But a `LogicGroup` only ever ANDs
its conditions — it has no equivalent top-level "or" — so the same
same-field-alternatives detection cannot be expressed the same way inside
a group; the store-group path needed its own transform, which TASK-2315
never added.

**Fix**: added `_collapse_same_field_alternatives()` — folds same-field
`EQ` conditions into one `FieldCondition(operator=IN, value=[...])` before
they're copied into each store-group `LogicGroup`, called immediately
before `_map_store_group_rule` in the `if store_groups:` branch. This is
the exact shape spec §2's own worked example already uses
(`FieldCondition(field_id="field_9050", operator="in", value=["4782",
"4783"])`), so the fix is bringing the store-group path in line with
spec intent, not inventing new behavior. Conditions on genuinely
different fields are left untouched and still AND, matching the flat
path's own reasoning.

**Verification of the fix**: re-ran the reviewer's exact repro (two
`block_logic_groups` on `field_9050` with values `4784`/`4782`, plus
`store_groups=["Ring of Fire","Epson Test Store"]`) — all 4
answer × store combinations that were previously stuck `visible=False`
now correctly resolve `visible=True`. Added two permanent regression
tests: `test_store_group_collapses_same_field_alternatives_into_in`
(asserts the collapsed `IN` shape) and
`test_store_group_alternatives_evaluate_for_either_answer_value`
(end-to-end `_eval_rule` pass proving EITHER alternative answer fires at
a matching store, and neither fires at a non-matching one). Full suite
re-run after the fix: identical 40-failure baseline (diffed explicitly),
2222 passed (2220 prior + 2 new). `ruff check` — same 7 pre-existing
findings, zero new.

The review's other two findings were addressed separately: the
`_extract_visit_context` field-name-collision risk (🟠 IMPORTANT) is
already explicitly documented as a flagged design tradeoff in both the
code docstring and TASK-2316's own Completion Note — left as-is per the
review's own framing ("not a blocker given the documented tradeoff...
should be an explicit decision"), since it is low-probability (import-
based field IDs are always `field_<column>`-shaped, never literally
`visit_context`) and non-crashing. The 🟡 suggestion (widen the two
pre-existing test doubles to accept `**kwargs` instead of having
production code branch around them) is noted for a future, separate,
low-priority cleanup — out of this task's file scope to fix here.
