# TASK-3241: Start, next, and issue-promotion workflow twins

**Feature**: FEAT-566 — SDD Work Ledger
**Spec**: `sdd/specs/sdd-work-ledger.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3226, TASK-3232, TASK-3236
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 12. Workers see relevant discoveries before coding, starts are recorded, and scheduling workflows surface/promote ready ledger issues on all twins.

## Scope

- Add ledger-context priming and `task.started` emission to sdd-start twins.
- Add ready-ledger-issue display to sdd-next twins.
- Add explicit `sdd-task --from-issue <id>` promotion guidance to task twins while retaining allocator discipline.
- Extend parity tests.

**NOT in scope**: automatic promotion, task closure, or done gate/snapshot flow.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-start.md` | MODIFY | Claude start steps. |
| `.agent/workflows/sdd-start.md` | MODIFY | Antigravity start steps. |
| `.agents/skills/sdd-start/SKILL.md` | MODIFY | Codex start steps. |
| `.claude/commands/sdd-next.md` | MODIFY | Claude issue display. |
| `.agent/workflows/sdd-next.md` | MODIFY | Antigravity issue display. |
| `.agents/skills/sdd-next/SKILL.md` | MODIFY | Codex issue display. |
| `.claude/commands/sdd-task.md` | MODIFY | Claude promotion guidance. |
| `.agent/workflows/sdd-task.md` | MODIFY | Antigravity promotion guidance. |
| `.agents/skills/sdd-task/SKILL.md` | MODIFY | Codex promotion guidance. |
| `tests/sdd/test_ledger_workflow_twins.py` | MODIFY | Parity tests. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
`LedgerService.get_context` is TASK-3232; `wikitoolkit ledger ready/open` is TASK-3236; the three `.agents/skills` files are Codex twins.

### Existing Signatures to Use
The ID allocator remains `python -m scripts.sdd.reserve_ids`; promotion must not hand-compute task IDs.

### Does NOT Exist
- ~~automatic ledger issue promotion~~ — promotion stays explicit.
- ~~task-start ledger event in twins~~ — this task adds it.

## Acceptance Criteria

- [x] Start primes before implementation and records `task.started` best-effort.
- [x] Next displays ready tasks and ledger issues.
- [x] Promotion preserves ID/dependency discipline and links source issue.
- [x] Twin parity assertions pass.

## Test Specification

Assert shared-root ledger commands and equivalent ordered steps in each platform.

### Completion Note

The dispatched gemini attempt exhausted its turn budget after touching
only 1 of the 10 declared files (`.claude/commands/sdd-start.md`) and
never committed — flagged `failed` by the merge gate and discarded (never
committed, so nothing was lost). Reimplemented directly across all 10
files: `--from-issue`/ledger-context priming/`task.started` emission
guidance added consistently to all three platform twins for
start/next/task.

Also reconciled the parallel-dispatch file-collision hazard from
TASK-3240/TASK-3242 (see their Completion Notes): added this task's own
tests as a third class, `TestStartNextTwins`, in the shared
`tests/sdd/test_ledger_workflow_twins.py` alongside the two already
reconciled there, rather than overwriting the file again.

`pytest tests/sdd/ -q` → 17 passed (4 for this task's own
`TestStartNextTwins`, plus the previously-reconciled 13). `ruff check` /
`black --check` clean. File fidelity: exactly the 10 declared files
touched, pure additions (0 deletions) in every one.

Seat: gemini (google-compat) · Backend: none (dev-loop attempt exhausted
budget uncommitted) · Attempts: 1 (failed, discarded) + 1 (sdd-worker
rewrite). Native rewrite done directly in the feature worktree.

