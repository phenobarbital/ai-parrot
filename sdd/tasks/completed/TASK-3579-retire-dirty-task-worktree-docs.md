# TASK-3579: Correct the operator docs and supersede FEAT-549's AC-22

**Feature**: FEAT-587 — Retire the `dirty_task_worktree` contract
**Spec**: `sdd/specs/fixgroup-05941da3dd5f.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

**discovered_from**: `issue:88b5c7d679c1`

---

## Context

Commit `ed267c217` made the engine extract and commit a sandboxed coder seat's
declared files instead of rejecting the attempt as `dirty_task_worktree`. Two
written contracts still say the opposite, and both are read by humans making
decisions:

- `docs/dev_loop/sdd-coder-orchestrator.md:433-434` tells operators *"nothing is
  merged until the branch is clean"* — an operator debugging a run will look for
  a rejection that no longer happens.
- `sdd/specs/sdd-worker-subagents.spec.md:818` — FEAT-549's **AC-22**, *"A task
  worktree with uncommitted or untracked changes is never merged
  (`dirty_task_worktree`)"* — is now directly contradicted by the deliberate
  design recorded in `mem-c163c2dde8ff`. Its origin, the S5 design-research row
  at `:1170`, says the same.

## Scope

Rewrite the operator-facing bullet to describe the real behaviour, and annotate
AC-22 and its S5 row as superseded by FEAT-587.

**NOT in scope**:
- Any code change — that is TASK-3578.
- **Deleting** AC-22 or the S5 row. FEAT-549 is a completed feature and its spec
  is a historical record; it gets an annotation, not an edit that erases what was
  decided at the time.
- Any other acceptance criterion in `sdd-worker-subagents.spec.md`.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/dev_loop/sdd-coder-orchestrator.md` | MODIFY | Replace the `dirty_task_worktree` error bullet with the extract-and-commit behaviour |
| `sdd/specs/sdd-worker-subagents.spec.md` | MODIFY | Annotate AC-22 (`:818`) and the S5 row (`:1170`) as superseded by FEAT-587 |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` on 2026-09-21. Documentation only — no imports, no
> signatures, no runtime behaviour.

### Verified anchors

```
docs/dev_loop/sdd-coder-orchestrator.md:433   - **`dirty_task_worktree`** — the coder left uncommitted or untracked
docs/dev_loop/sdd-coder-orchestrator.md:434     changes; nothing is merged until the branch is clean.
sdd/specs/sdd-worker-subagents.spec.md:818    - [ ] **AC-22 (S5)** A task worktree with uncommitted or untracked changes is never merged (`dirty_task_worktree`).
sdd/specs/sdd-worker-subagents.spec.md:1170   | S5 | Reject dirty/untracked coder worktrees before merge (risk, high) | **CONFIRM** | ...
```

Behaviour to describe, verified in source:
`_commit_declared_changes` (`engine.py:2069`) stages only `parse_task_files(task_md)`,
never `DevelopmentOutput.files_changed` and never an `sdd/` path; an undeclared
leftover returns `outcome="fidelity_violation"` with `unexpected_files` and the
diagnostic prefix `undeclared_files_left_uncommitted`.

### Does NOT Exist

- ~~a second `dirty_task_worktree` bullet in the docs~~ — exactly one occurrence (verified `grep -cF`).
- ~~`.claude/worktrees/feat-FEAT-564-…--pool/docs/dev_loop/sdd-coder-orchestrator.md`~~ — a stale worktree copy. Edit only the main checkout's file.
- ~~`.claude/worktrees/zz-baseline-feat574/docs/…`~~ — likewise stale.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "docs/dev_loop/sdd-coder-orchestrator.md",
      "action": "MODIFY"
    },
    {
      "path": "sdd/specs/sdd-worker-subagents.spec.md",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Match the surrounding markdown style: the docs file uses `- **\`code\`** — prose` bullets wrapped at roughly 75 columns.
- Annotate, never delete, in the FEAT-549 spec.

### References in Codebase
- `mem-c163c2dde8ff` — the decision record.
- `ed267c217` — the implementing commit; cite it in both annotations.

---

## Implementation Blueprint

### Steps (in order)

1. Rewrite the docs bullet, because an operator reading the current text will
   hunt for a rejection the engine no longer performs.
2. Annotate AC-22, because a completed spec that states the opposite of the
   shipped behaviour will be quoted back as authority by the next agent.
3. Annotate the S5 row the same way, because it is where AC-22 came from.

### `docs/dev_loop/sdd-coder-orchestrator.md` (MODIFY — step 1)

```markdown
# occurrences: 1 (verified: grep -cF -e '- **`dirty_task_worktree`** — the coder left uncommitted or untracked' docs/dev_loop/sdd-coder-orchestrator.md)
# REPLACE the two lines at :433-434 with:
- **uncommitted coder deliveries** — a sandboxed seat has `.git` read-only by
  design and cannot commit; the engine extracts the task's **declared** files
  itself and commits them on the attempt branch (`_commit_declared_changes`,
  FEAT-587 / ed267c217). There is no `dirty_task_worktree` rejection. A file the
  coder produced but the task does not declare is never merged and never
  dropped: it surfaces as `fidelity_violation` with `unexpected_files` and the
  `undeclared_files_left_uncommitted` diagnostic.
```

**Why**: the bullet sits in the operator-facing error-code list, so it must say
what an operator will actually observe, and name the outcome they should look
for instead.

### `sdd/specs/sdd-worker-subagents.spec.md` (MODIFY — step 2)

```markdown
# occurrences: 1 (verified: grep -cF '**AC-22 (S5)**' sdd/specs/sdd-worker-subagents.spec.md)
# REPLACE the line at :818 with:
- [ ] ~~**AC-22 (S5)** A task worktree with uncommitted or untracked changes is never merged (`dirty_task_worktree`).~~ **— SUPERSEDED by FEAT-587** (`ed267c217`): `.git` is read-only to a sandboxed coder seat by design, so the engine extracts and commits the task's declared files itself; only *undeclared* leftovers block the merge, as `fidelity_violation`. See `mem-c163c2dde8ff`.
```

**Why**: strike-through plus an explicit supersession keeps the historical record
intact while making it impossible to quote the criterion as current.

### `sdd/specs/sdd-worker-subagents.spec.md` (MODIFY — step 3)

```markdown
# occurrences: 1 (verified: grep -cF '| S5 | Reject dirty/untracked coder worktrees before merge (risk, high) |' sdd/specs/sdd-worker-subagents.spec.md)
# APPEND to the final cell of the S5 row at :1170, inside the existing table row:
 **SUPERSEDED by FEAT-587 (ed267c217)** — the clean-status precondition was removed; see AC-22.
```

**Why**: the row is the design-research origin of AC-22; leaving it unannotated
would let the same decision be re-derived from the research table.

### FILL IN checklist

- [ ] none — every replacement is fully specified above

---

## Acceptance Criteria

- [ ] `docs/dev_loop/sdd-coder-orchestrator.md` describes the extract-and-commit behaviour; no sentence claims a dirty branch blocks the merge (AC-6)
- [ ] FEAT-549 AC-22 and its S5 row are annotated as superseded by FEAT-587, citing `ed267c217` (AC-7)
- [ ] Neither annotation deletes the original text
- [ ] No code file is modified by this task

## Validation Commands

- `pytest tests/sdd_scripts/test_doc_taxonomy.py -q`
- `pytest tests/sdd_scripts/test_sdd_spec_intake_contract.py -q`

> Both files are verified to exist. They are the repository's checks over the
> `sdd/` document tree, which this task edits; there is no code change here for
> a unit test to cover.

## Test Specification

Documentation-only task; correctness is verified by the acceptance criteria and
by `grep` for the retired term:

```bash
grep -rn "dirty_task_worktree" docs/dev_loop/sdd-coder-orchestrator.md
# expected: no hit, or only inside the FEAT-587 supersession note
```

---

## Completion Note

**Completed by**: claude-opus-5 (session 7e0222c8)
**Date**: 2026-09-21
**Notes**: Replaced the operator-facing `dirty_task_worktree` bullet with a
description of the extract-and-commit behaviour, naming `fidelity_violation` /
`unexpected_files` / `undeclared_files_left_uncommitted` as what an operator
should actually look for. Annotated FEAT-549's AC-22 (strike-through plus an
explicit supersession note) and its S5 design-research row at `:1170`; neither
original text was deleted, since FEAT-549 is a completed feature and its spec
is a historical record.

One `dirty_task_worktree` mention survives in the docs, inside the FEAT-587
note itself ("There is no `dirty_task_worktree` rejection") — allowed by this
task's Test Specification.

Validation: `tests/sdd_scripts/test_doc_taxonomy.py` +
`test_sdd_spec_intake_contract.py` 9 passed. No code file touched.

**Deviations from spec**: none
