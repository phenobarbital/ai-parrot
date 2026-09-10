# TASK-3095: Spec template — Interface Skeleton sub-block + §9 Design Research Cross-Check

**Feature**: FEAT-545 — Collaborative Adversarial Spec Design
**Spec**: `sdd/specs/collaborative-adversarial-spec-design.spec.md` (§3 Module 3, §2 New Public Interfaces)
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Blueprints (TASK-3093/3094) are derived from *Interface Skeletons* the spec fixes per module (spec G2), and the Codex design-research phase (TASK-3097) records its triage in a spec **§9** (spec G3/U2). Both are template additions to `sdd/templates/spec.md`. Additive only: no existing heading renamed (spec AC-13).

---

## Scope

- Add an "Interface Skeleton" bullet to both module examples in `## 3. Module Breakdown`.
- Insert `## 9. Design Research Cross-Check` after `## 8. Open Questions` and before `## Revision History`.

**NOT in scope**: `/sdd-spec` command text (TASK-3097); design-research prompt/schema files (TASK-3096).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `sdd/templates/spec.md` | MODIFY | Skeleton bullets in §3 (2×); new §9 block (~15 lines) |

---

## Codebase Contract (Anti-Hallucination)

### Anchors in `sdd/templates/spec.md` (195 lines, verified 2026-09-10)
```text
:72   ## 3. Module Breakdown
:77   ### Module 1: <Name>
:78   - **Path**: `parrot/path/to/module.py`
:79   - **Responsibility**: What this module does
:80   - **Depends on**: existing module or Module N from this spec       ← add skeleton bullet AFTER this line
:83   ### Module 2: <Name>
:86   - **Depends on**: Module 1                                        ← add skeleton bullet AFTER this line
:182  ## 8. Open Questions
:186-187  - [ ] Question 1 — *Owner: name* / - [ ] Question 2 — *Owner: name*
:189  ---
:191  ## Revision History                                               ← INSERT §9 (with its own trailing "---") BEFORE this heading
```
Separator convention: blank, `---`, blank between `## ` sections.

### Does NOT Exist
- ~~`## 9. Design Research Cross-Check`~~ / ~~`Interface Skeleton`~~ — created here
- ~~`## 9. Implementation Blueprints (per module)`~~ — exists in ONE old spec (`sdd/specs/formdesigner-field-uid.spec.md:853`) as a bespoke section; do NOT add it to the template — FEAT-545 puts blueprints in task files, not specs

---

## Implementation Notes

### Key Constraints
- Skeleton sub-block uses a 2-space indented fenced ```python block under a bullet, as in the blueprint below (markdown renders it as part of the list item).
- §9 table columns are fixed by the spec: `# | Suggestion (kind) | Disposition | Reason | Landed in`.

---

## Implementation Blueprint

### Steps (in order)
1. Add the Interface Skeleton bullet under Module 1 and Module 2 — *why*: `/sdd-spec` §4 will require one per module (TASK-3097); the template must show the shape.
2. Insert §9 before `## Revision History` — *why*: the numbered sections must stay contiguous (§8 → §9 → Revision History).
3. `grep -n "^## " sdd/templates/spec.md` and confirm order 1…9 then Revision History.

### `sdd/templates/spec.md` (MODIFY — after `- **Depends on**: ...` in Module 1 and Module 2)
````markdown
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```python
  # parrot/path/to/module.py  (new | modifies parrot/path/to/module.py:NN)
  class NewComponent(ExistingBase):  # ExistingBase verified: parrot/base.py:NN
      """<purpose>."""
      async def method(self, param: Type) -> ReturnType:
          """<contract: returns …; raises … when …>."""
  ```
````

### `sdd/templates/spec.md` (MODIFY — insert before `## Revision History`)
````markdown
## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `<model>` · Status: completed | skipped (<reason>)
> · Transcript: `sdd/state/<FEAT-ID>/design_research/`
> Every row is a suggestion the reviewer made; the disposition is the spec author's
> call (CONFIRM = folded into the spec, REJECT = reason recorded, ESCALATE = §8 question).

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | <title> (architecture) | CONFIRM | <why adopted> | §2 Overview |
| S2 | <title> (testing) | REJECT | <why not> | — |
| S3 | <title> (risk) | ESCALATE | <what the human must decide> | §8 Q<N> |

Summary: **<C>** confirmed · **<R>** rejected · **<E>** escalated.

---

````

### FILL IN checklist
- [ ] none — template text fully specified

---

## Acceptance Criteria

- [ ] `grep -c "Interface Skeleton" sdd/templates/spec.md` → `2`
- [ ] `grep -n "^## 9. Design Research Cross-Check" sdd/templates/spec.md` → one line, before `## Revision History`
- [ ] `grep -n "^## " sdd/templates/spec.md` shows §1…§9 in order, then `## Revision History` (spec AC-3, AC-13)
- [ ] Only `sdd/templates/spec.md` changed

---

## Test Specification

Automated in TASK-3098 (`test_spec_template_has_skeleton_and_section_9`). Manual now: the three greps above.

---

## Agent Instructions

1. Read spec §3 Module 3 and §2 "New Public Interfaces".
2. Dependencies: none (parallel-safe with TASK-3093/3096).
3. Re-grep anchors; implement from the blueprint; verify; commit `sdd/templates/spec.md` only.
4. Move to completed; index → `"done"`; Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
