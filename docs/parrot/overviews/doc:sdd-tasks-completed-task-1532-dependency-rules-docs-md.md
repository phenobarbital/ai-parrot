---
type: Wiki Overview
title: 'TASK-1532: Documentation — dependency/operation/post-dependency reference'
id: doc:sdd-tasks-completed-task-1532-dependency-rules-docs-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §5 Acceptance Criteria requires documentation. This task writes the
  formdesigner reference for
relates_to:
- concept: mod:parrot.forms
  rel: mentions
---

# TASK-1532: Documentation — dependency/operation/post-dependency reference

**Feature**: FEAT-234 — Form Designer — Conditional Sections (Pre/Post Dependencies)
**Spec**: `sdd/specs/formdesigner-conditional-sections.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1526, TASK-1527, TASK-1528, TASK-1529, TASK-1530, TASK-1531
**Assigned-to**: unassigned

---

## Context

Spec §5 Acceptance Criteria requires documentation. This task writes the formdesigner reference for
pre-dependencies (with the new `xor`/`not` logic), operations/calculated values, post-dependencies,
authoring via `EditToolkit`, and the optional `RuleEvaluator`. Runs last so it documents the
shipped behavior.

---

## Scope

- Add/extend the formdesigner docs (locate the existing formdesigner doc set under `docs/` — likely
  `docs/` or the package's docs) with a "Conditional Sections — Pre/Post Dependencies" reference:
  - `depends_on` with `and|or|xor|not` + `effect` + optional `operations`.
  - `DependencyOperation` vocabulary (copy/arithmetic/string-date/lookup-aggregate).
  - `post_depends` (`PostDependency`) forward effects.
  - Authoring via `EditToolkit` (`add_dependency`/`add_post_dependency`/...) and control-registry
    capability metadata + helper snippets.
  - Optional `RuleEvaluator.resolve()` for server-side resolution; note renderers MAY ignore rules.
  - Document the resolved `NOT` default (negates the AND-group) and the open questions
    (`reload_options` timing, ARRAY-operand scope) as "current behavior / future work".
- Include at least one end-to-end example (a form with an xor `depends_on`, an arithmetic operation,
  and a `set` post-dependency) shown as JSON.

**NOT in scope**: code changes; tests (this is docs-only).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/...` (formdesigner doc set — confirm exact path) | CREATE/MODIFY | Pre/post dependency + operations reference |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports (for accurate doc examples)
```python
from parrot_formdesigner.core import (
    FormSchema, FormField, FieldType,
    DependencyRule, FieldCondition, ConditionOperator,
    DependencyOperation, PostDependency,
)
from parrot_formdesigner.services import FormValidator, RuleEvaluator, RuleResolution
from parrot_formdesigner.tools import EditToolkit, CreateFormTool
```

### Existing Signatures to Use (document these as shipped)
```python
DependencyRule(conditions=[...], logic="and|or|xor|not", effect="show|hide|require|disable",
               operations=[DependencyOperation(...)] | None)
DependencyOperation(op="copy|add|subtract|multiply|divide|percent|concat|format|date_diff|lookup|aggregate",
                    operands=[...], target="...", options={...} | None)
PostDependency(target="...", effect="set|calc|reload_options|show|hide|require|cascade_clear",
               conditions=[...] | None, logic="and|or|xor|not", operation=DependencyOperation(...) | None)
RuleEvaluator().resolve(form, answers, *, locale="en") -> RuleResolution  # visible/required/computed/cleared
```

### Does NOT Exist
- ~~Nested boolean condition trees~~ — document as future work (spec §1 Non-Goals); v1 logic is flat.
- ~~Container-level `post_depends`~~ — `FormSubsection`/`FormSection` do NOT have `post_depends` in v1.
- Do NOT document methods/fields not actually shipped by TASK-1523..1531 — verify each example against the code.

---

## Implementation Notes

### Pattern to Follow
Match the structure/tone of existing formdesigner docs (find them first — check `docs/` for
formdesigner pages). Keep examples runnable/constructable against the real models.

### Key Constraints
- Every code example must construct against the shipped models — verify, don't guess.
- Note explicitly that renderers MAY interpret or ignore rules (spec acceptance criterion).

### References in Codebase
- Existing formdesigner docs (locate under `docs/`).
- The shipped modules from TASK-1523..1531.

---

## Acceptance Criteria

- [ ] Reference page documents `depends_on` (and/or/xor/not), `operations`, and `post_depends`.
- [ ] Authoring (`EditToolkit`) and optional `RuleEvaluator` are documented.
- [ ] At least one end-to-end JSON example is included and is consistent with the shipped schema.
- [ ] `NOT` semantics + open questions are documented as current/future behavior.
- [ ] Docs build/lint (if the docs toolchain runs in CI) without errors.

---

## Test Specification

> Docs-only task — no automated tests. Validation is review + (optionally) constructing each
> example model in a scratch REPL to confirm it is valid.

---

## Agent Instructions

1. **Read the spec** (whole) + the shipped code from TASK-1523..1531.
2. **Check dependencies** — all listed tasks in `sdd/tasks/completed/`.
3. **Locate the existing formdesigner doc set** before writing.
4. **Update index** → `"in-progress"`.
5. **Write** the reference + example; verify examples against the models.
6. **Verify** acceptance criteria.
7. **Move** to `sdd/tasks/completed/`; **update index** → `"done"`; fill Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.6)
**Date**: 2026-06-12
**Notes**: Created `docs/formdesigner-conditional-sections.md` with 11 sections: pre-dependencies (logic gates, effects, operators), DependencyOperation vocabulary with all 11 op kinds, PostDependency forward effects, an end-to-end JSON + Python example covering xor/arithmetic/set patterns, EditToolkit CRUD authoring guide, control-registry capability metadata, get_dependency_rule_snippets, RuleEvaluator server-side evaluation, YAML serialization, JSON Schema x-extensions round-trip, open questions (reload_options/aggregate/lookup/nested trees), validation, and legacy parrot.forms re-exports. All examples use shipped model signatures.

**Deviations from spec**: None.
