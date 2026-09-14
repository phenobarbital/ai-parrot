# TASK-3241: Start, next, and issue-promotion workflow twins

**Feature**: FEAT-566 — SDD Work Ledger
**Spec**: `sdd/specs/sdd-work-ledger.spec.md`
**Status**: pending
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

- [ ] Start primes before implementation and records `task.started` best-effort.
- [ ] Next displays ready tasks and ledger issues.
- [ ] Promotion preserves ID/dependency discipline and links source issue.
- [ ] Twin parity assertions pass.

## Test Specification

Assert shared-root ledger commands and equivalent ordered steps in each platform.

