---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: Store-Context Conditions in the Rules Engine

**Feature ID**: FEAT-440
**Date**: 2026-08-21
**Author**: Juan Franco (spec drafted with Claude Code)
**Status**: draft
**Target version**: 0.9.3

> Source evidence: `Recap_10.xlsx` — the Recap Definition v390 export of
> NetworkNinja form `db-form-10-69` (Epson Visit Form), 1.475 rows.
> Measured against `navigator_staging` on 2026-08-20/21.
> Downstream halves, reserved separately: fieldsync (data + context
> assembly) and navigator-svelte (client rule engine).

---

## 1. Motivation & Business Requirements

### Problem Statement

A NetworkNinja form gates its blocks and questions on **two independent
axes**, and the engine can express only one of them.

The first axis is an answer: *"show this block when the visit type is Brand
Ambassador or Assisted Sales"*. That works today.

The second is the **store the visit is at**, and it is not an answer to
anything — it is context the rep never types. On the Epson Visit Form,
measured against the source export:

| | count |
|---|---|
| blocks gated on a store group | 6 of 17 |
| questions gated on a store group | 91 of 295 |
| distinct store groups in use | 11 (of 36 defined) |
| elements gated on BOTH axes at once | 26 |
| …of those, needing AND-of-ORs | 23 |

The clearest case is the `Ring of Fire Photos` block (source `block_id` 26,
13 questions, 4 of them required). Measured over 883 visits in the three
months after the form's 2026-05-08 revision: it appears in **exactly 20
stores and in 254 others never**, with **zero** stores in between. It is a
curated list, reproducible from no attribute we hold — the closest rule
(`market_trainer_name = 'Joe Montoya' AND retailer_type = 'Direct'`) yields
20 true positives and 17 false ones.

Two distinct gaps stop the engine short.

**1 — No operator asks the question.** `ConditionOperator.IN` asks whether
the answer is one of several values. Store membership is the mirror image:
the context supplies the list (`["Best Buy", "Epson Test Store", "Ring of
Fire"]`) and the rule names the single entry it needs. Nothing expresses
that direction.

**2 — `DependencyRule` cannot nest.** It carries a flat `conditions` list
under one `logic` gate, so *"the store is in one of these 8 groups AND the
visit is one of these 5 types"* — the real shape of the `Compliance Images`
block — is inexpressible: `and` demands all thirteen conditions hold,
`or` settles for any one. Neither is the rule.

The condition SOURCES already exist. `FieldCondition.source` accepts
`"location_variable"` and `"visit_context"`, `_eval_condition` resolves
both, and `RuleEvaluator.resolve()` takes `location_vars` / `visit_context`
parameters (FEAT-301, `sdd/specs/conditional-logic-engine.spec.md`, approved).
What is missing is the vocabulary to *use* them for set membership, and the
nesting to combine them with an answer condition.

### Goals

- Express "this multi-valued context source holds this value" as a
  first-class operator, usable by any condition source.
- Restore nesting to `DependencyRule` so one rule can require an
  alternative on one axis AND an alternative on another.
- Match the frontend's existing `LogicGroup` contract exactly
  (navigator-svelte `src/lib/formbuilder/types/schema.ts`), which has
  evaluated groups since before the server could express them.
- Keep every rule that does not use the new shape behaving identically.
- Have the networkninja importer emit store-group conditions instead of
  discarding the column.
- Accept and propagate a caller-supplied store context through the HTTP
  surface that serves and validates forms.

### Non-Goals (explicitly out of scope)

- **Sourcing store-group membership.** It exists in NO replicated table —
  verified across `networkninja.stores` (39 columns + the full 43-key
  `custom_fields` inventory), `epson.stores*`, and every `*group*` table
  (`epson.trait_groups` has the right shape and is empty). It lands in
  `<tenant>.fs_stores` and is the fieldsync half.
- **Assembling the context.** Which store a visit belongs to is FieldSync's
  knowledge, not this package's. This spec only accepts what it is handed.
- **The client rule engine.** `DependencyCondition` in navigator-svelte has
  no `source`/`key` and cannot evaluate a context condition at all; that is
  its own feature.
- **`location_variable` conditions.** The source is already supported and
  untouched here; only `visit_context` is exercised.
- **Page-level hierarchy.** NetworkNinja groups its 17 blocks into 10 named
  pages. Real, and a separate concern from conditions.

---

## 2. Architectural Design

### Overview

Two additions to `core`, one evaluation change in `services`, and two
plumbing changes at the edges.

```
core/constraints.py
  ConditionOperator  += CONTAINS, NOT_CONTAINS
  LogicGroup          (new)  conditions: list[FieldCondition]
  DependencyRule     += groups: list[LogicGroup] | None

core/resolution.py
  resolve_rule_references()  also walks conditions INSIDE groups

services/rule_evaluator.py
  _holds()      (new)  set-membership over a possibly-scalar source
  _eval_rule()  (new)  the ONE place a DependencyRule is evaluated

tools/services/networkninja.py
  emits a visit_context CONTAINS condition per store group

api/handlers.py
  accepts a store context and hands it to resolve()/validate()
```

### Integration Points

- **`_eval_rule` is the single evaluation seam.** Field rules, section
  rules and post-dependencies route through it, so groups work everywhere
  at once rather than in whichever call site remembered.
- **Resolution must walk groups.** `_eval_condition` reads a field
  condition's answer through `field_uid`; a grouped condition left
  unresolved keeps `field_uid=None` and can never match. This is the exact
  defect class that made every imported networkninja rule inert
  (`mem-bcb5469d8eb0`), and a new nesting level reintroduces it silently
  unless resolution follows.
- **`FormValidator.validate()`** already threads `visit_context` through to
  the evaluator; nothing further is needed there.

### Data Models

```python
class LogicGroup(BaseModel):
    """One alternative: conditions AND'd inside, groups OR'd between."""
    model_config = ConfigDict(extra="forbid")
    conditions: list[FieldCondition]


class DependencyRule(BaseModel):
    groups: list[LogicGroup] | None = None   # replaces conditions/logic when set
    conditions: list[FieldCondition]
    logic: Literal["and", "or", "xor", "not"] = "and"
    effect: Literal["show", "hide", "require", "disable"] = "show"
```

A store-gated block, as the importer should emit it:

```python
DependencyRule(conditions=[], effect="show", groups=[
    LogicGroup(conditions=[
        FieldCondition(source="visit_context", key="store_groups",
                       operator="contains", value="Ring of Fire"),
        FieldCondition(field_id="field_9050", operator="in",
                       value=["4782", "4783"]),   # Brand Ambassador | Assisted Sales
    ]),
])
```

---

## 3. Module Breakdown

### Module 1: `CONTAINS` / `NOT_CONTAINS`

Two enum members and a `_holds` helper. Semantics that must hold:

- A list/tuple/set source matches when it holds the value.
- A **scalar source counts as a one-element collection**, so a store in
  exactly one group still matches.
- A **string source is NOT walked character by character** — `"Ring of
  Fire"` must not contain `"Fire"`. This is the trap in using `in`
  directly and is the reason for a helper rather than an inline expression.
- A missing source is `False`, never an error.

### Module 2: `LogicGroup` + `_eval_rule`

The model, its export from `core/__init__`, and the collapse of the three
`_eval_logic(rule.conditions, rule.logic, …)` call sites into `_eval_rule`.
An empty `groups` list falls back to the flat pair — the same reading
`_eval_logic` gives an empty condition list, not "nothing can satisfy this".

### Module 3: Resolution through groups

`resolve_rule_references` gains an inner `_resolve_rule` applied to both
field and section rules, walking `rule.conditions` and every
`group.conditions`. Context conditions carry no field reference and are
skipped, as they already are in the flat path.

### Module 4: Importer emission

`NetworkninjaFormService` currently reads structure from
`forms.question_blocks`, where the store-group condition **does not
appear** — it lives only in the Recap Definition export. This module
defines the mapping from a per-element list of store-group names to a
`LogicGroup`, and wires it wherever that list becomes available. Until the
source supplies it, the mapping is exercised by fixtures only.

### Module 5: HTTP passthrough

The render and validate handlers accept a store context from the caller and
pass it as `visit_context`. Absent context means no context: a rule that
asks about a store the caller did not describe does not fire, which fails
closed.

---

## 4. Test Specification

### Unit Tests

`CONTAINS`: list holding the value; list without it; scalar as a
one-element collection; a string source NOT matching a substring; missing
context; `NOT_CONTAINS` as the exact negation.

`LogicGroup`: both halves satisfied; right store + wrong visit type; right
visit type + wrong store; a second group as an alternative; groups
overriding a flat list that would say otherwise; an empty group list
falling back; section rules honouring groups.

Resolution: a grouped field condition gets its `field_uid`; the same for a
section rule's groups; a grouped context condition resolves without raising
and keeps `field_uid=None`.

### Test Data / Fixtures

Built from the real gating of `db-form-10-69`: the `Ring of Fire` group and
the `field_9050` visit-type driver, so the fixture asserts the shape the
source actually produces rather than an invented one.

---

## 5. Acceptance Criteria

- **AC1** A rule whose group requires `store_groups CONTAINS "Ring of Fire"`
  AND `field_9050 IN [Brand Ambassador, Assisted Sales]` shows only when
  both hold, and stays hidden when either fails or the context is absent.
- **AC2** `CONTAINS` against the string `"Ring of Fire"` does not match
  `"Fire"`.
- **AC3** A store in one group, supplied as a scalar, matches.
- **AC4** Two groups behave as alternatives.
- **AC5** A rule without `groups` produces byte-identical behaviour to
  before, verified by the existing suite passing unchanged.
- **AC6** Every condition inside a group carries a resolved `field_uid`
  after `resolve_rule_references`, and a context condition does not.
- **AC7** Section rules, field rules and post-dependencies all honour
  groups, because all three route through `_eval_rule`.
- **AC8** The failing-test set is identical to `dev`'s before and after —
  no regression is absorbed into the pre-existing count.

---

## 6. Codebase Contract

### Verified Imports

```python
from parrot_formdesigner.core.constraints import (
    ConditionOperator, DependencyRule, FieldCondition, LogicGroup,
)
from parrot_formdesigner.core.resolution import resolve_rule_references
from parrot_formdesigner.services.rule_evaluator import RuleEvaluator
```

### Existing Signatures This Builds On

```python
# services/rule_evaluator.py — already accept the context, nothing populates it
async def RuleEvaluator.resolve(form, answers, *, locale="en",
                                location_vars=None, visit_context=None) -> RuleResolution
def _eval_condition(condition, answers, form, location_vars=None, visit_context=None) -> bool
    # source == "visit_context" -> raw = (visit_context or {}).get(condition.key)

# services/validators.py — threads the context to the evaluator
async def FormValidator.validate(form, data, *, locale="en", auth_context=None,
                                 location_vars=None, visit_context=None) -> ValidationResult
```

### Frontend Contract to Match

```ts
// navigator-svelte src/lib/formbuilder/types/schema.ts
export interface LogicGroup { conditions: DependencyCondition[] }
export interface DependencyRule {
  groups?: LogicGroup[]   // AND inside, OR between; replaces conditions/logic
  conditions: DependencyCondition[]
  logic?: 'and' | 'or'
  effect?: DependencyEffect
}
```

---

## 7. Risks

- **A new nesting level is a new place for references to go unresolved.**
  Mitigated by Module 3 and AC6; the failure is silent by nature, so the
  test is the control, not review.
- **Nothing produces the context yet.** Until fieldsync supplies it, every
  store-gated rule fails closed and the affected elements stay hidden. That
  is why the importer must not emit these conditions against a live form
  before its half lands — a correct rule with no context is stricter than
  no rule at all.
- **The client cannot evaluate these conditions.** Shipping server-side
  enforcement before the client understands the same rules reproduces, in
  mirror, the divergence between what the rep sees and what the server
  validates.
