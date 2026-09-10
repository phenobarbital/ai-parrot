# TASK-3093: Task template — add the Implementation Blueprint section

**Feature**: FEAT-545 — Collaborative Adversarial Spec Design
**Spec**: `sdd/specs/collaborative-adversarial-spec-design.spec.md` (§2 New Public Interfaces, §3 Module 1)
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Non-thinking executors (Haiku/Sonnet) read a `TASK-*.md` file and write code to disk. Today the task template gives them anchors (Codebase Contract) but not the *shape* of the code they must produce. This task adds the "## Implementation Blueprint" section to `sdd/templates/task.md` — the structure every future task will carry (spec G1). The rules for filling it are added to `/sdd-task` in TASK-3094; this task only ships the template text.

---

## Scope

- Insert a new `## Implementation Blueprint` section into `sdd/templates/task.md` **after** `## Implementation Notes` and **before** `## Acceptance Criteria`.
- Update `## Agent Instructions` step 5 to start from the blueprint.
- Do not rename, remove, or reorder any existing heading (spec AC-13: additive only).

**NOT in scope**: `/sdd-task` command rules (TASK-3094); spec template (TASK-3095); tests (TASK-3098).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `sdd/templates/task.md` | MODIFY | Insert blueprint section (~45 lines) before `## Acceptance Criteria`; edit Agent Instructions step 5 |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` 2026-09-10. Re-grep headings before editing — line numbers shift, heading text does not.

### Existing anchors in `sdd/templates/task.md` (175 lines)
```text
:73   ## Implementation Notes
:77   ### Pattern to Follow
:86   ### Key Constraints
:92   ### References in Codebase
:96   ---                              ← the horizontal rule that closes Implementation Notes
:98   ## Acceptance Criteria           ← INSERT the new section immediately BEFORE this heading (after a "---")
:108  ## Test Specification
:147  ## Agent Instructions
:159  5. **Implement** following the scope, codebase contract, and notes above
:167  ## Completion Note
```
Section separator convention in this file: a blank line, `---`, a blank line between every `## ` section.

### Does NOT Exist
- ~~`## Implementation Blueprint`~~ / ~~`### FILL IN checklist`~~ — not present yet; this task creates them
- ~~`## Reference Implementation`~~ — the proposal's early name; do NOT use it, the approved name is "Implementation Blueprint"
- ~~`sdd/templates/task.md.j2`~~ or any templating engine — the template is plain markdown copied by the `/sdd-task` command

---

## Implementation Notes

### Pattern to Follow
Mirror the tone of the existing `## Codebase Contract (Anti-Hallucination)` block (`task.md:43-48`): a bold-CRITICAL blockquote explaining what the executor must do, then sub-headings with fenced examples. Prior art for the concept: `sdd/specs/formdesigner-field-uid.spec.md:853-860` ("Agents adapt mechanically … MUST NOT redesign").

### Key Constraints
- Keep placeholders in `<angle brackets>` like the rest of the template.
- The section is *template text*: it shows one CREATE example and one MODIFY example; real tasks replace them.
- Do not touch the frontmatter-free header lines 1-9.

---

## Implementation Blueprint

> Executor-ready. Write the block below into `sdd/templates/task.md` exactly where indicated, then complete the single `FILL IN`.

### Steps (in order)
1. Open `sdd/templates/task.md`; locate the line `## Acceptance Criteria` (currently :98) — *why*: insertion is anchored to heading text, not line number.
2. Insert the block below **before** that heading, keeping the `---` separator pattern — *why*: every `## ` section in this file is fenced by `---`.
3. Replace step 5 of `## Agent Instructions` — *why*: the executor must be told to start from the blueprint.
4. Run `grep -n "^## " sdd/templates/task.md` and confirm the heading order is: Context, Scope, Files to Create / Modify, Codebase Contract, Implementation Notes, **Implementation Blueprint**, Acceptance Criteria, Test Specification, Agent Instructions, Completion Note.

### `sdd/templates/task.md` (MODIFY — insert before `## Acceptance Criteria`)
````markdown
## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Blocks were derived
> from the spec's Interface Skeletons and re-verified against the Codebase Contract
> above when this task was written. This is NOT the full implementation:
> business-logic branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. <imperative step> — *why*: <one sentence>
2. <imperative step> — *why*: <one sentence>

### `parrot/path/to/new_file.py` (CREATE)
```python
"""<module docstring>."""
from __future__ import annotations

from parrot.module import ClassName  # verified: parrot/module/__init__.py:NN


class NewComponent(ClassName):
    """<one-line purpose>."""

    async def method(self, param: Type) -> ReturnType:
        """<what it returns and when it raises>."""
        self.logger.debug("method: %s", param)
        # FILL IN: <the exact decision left to you> — bounded by <constraint | AC-N>
        raise NotImplementedError
```
**Why this shape**: <2–4 sentences: which spec decision each block implements; what must NOT change>

### `parrot/path/to/existing.py` (MODIFY)
```python
# AFTER — insert below `<verbatim anchor line>` (verified: parrot/path/to/existing.py:NN)
<new lines>
```
**Why**: <1–2 sentences>

### FILL IN checklist
- [ ] `new_file.py::NewComponent.method` — <decision>; bounded by <constraint | AC-N>

---

````

### `sdd/templates/task.md` (MODIFY — `## Agent Instructions`, step 5)
```markdown
# BEFORE (verified: sdd/templates/task.md:159)
5. **Implement** following the scope, codebase contract, and notes above
# AFTER
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
```
**Why**: the executor's checklist must point at the new section, otherwise the blueprint is decorative.

### FILL IN checklist
- [ ] none — this task is fully specified (template text is the deliverable)

---

## Acceptance Criteria

- [ ] `grep -n "^## Implementation Blueprint" sdd/templates/task.md` returns exactly one line, and it precedes `## Acceptance Criteria`
- [ ] `grep -c "### Steps (in order)\|### FILL IN checklist\|\*\*Why this shape\*\*" sdd/templates/task.md` ≥ 3
- [ ] Heading order per Blueprint step 4 (no existing heading renamed/removed) — spec AC-2, AC-13
- [ ] Agent Instructions step 5 mentions "Implementation Blueprint" and "FILL IN"
- [ ] Existing task files (e.g. `sdd/tasks/active/TASK-3056-*.md`) are untouched (`git status` shows only `sdd/templates/task.md`)

---

## Test Specification

Template-only task; the automated check lands in TASK-3098 (`test_task_template_has_blueprint_section`). Manual check now:
```bash
grep -n "^## " sdd/templates/task.md
grep -n "FILL IN" sdd/templates/task.md
```

---

## Agent Instructions

1. Read the spec §2 "New Public Interfaces" and §3 Module 1.
2. Dependencies: none.
3. Verify the anchors in the Codebase Contract by grepping the heading text.
4. Update status in `sdd/tasks/index/collaborative-adversarial-spec-design.json` → `"in-progress"`.
5. Implement from the blueprint above.
6. Verify acceptance criteria; commit `sdd/templates/task.md` only.
7. Move this file to `sdd/tasks/completed/`, update index → `"done"`, fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
