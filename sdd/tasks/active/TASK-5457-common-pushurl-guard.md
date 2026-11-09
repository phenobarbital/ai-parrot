# TASK-5457: Refuse push-protection disable over a common push URL; forbid set-url bypass in /sdd-done

**Feature**: FEAT-865 fixgroup-eb6709b6a57b
**Spec**: `sdd/specs/fixgroup-eb6709b6a57b.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:d0c89274743b`

## Context
See spec §1. `git remote set-url --push` from a worktree poisons the common `.git/config`.

## Scope
- `disable()` raises `SyncError(EXIT_TARGET)` when the common config has `remote.origin.pushurl`.
- `status` message names a common push URL.
- One rule line in each sdd-done twin.
**NOT in scope**: auto-removing the common value; `enable()`.

## Files to Modify
- `packages/ai-parrot/src/parrot/sdd/scripts/worktree_push_protection.py`
- `tests/sdd_scripts/test_worktree_push_protection.py`
- `.claude/commands/sdd-done.md` + `packages/ai-parrot/src/parrot/sdd/_assets/claude/commands/sdd-done.md`
- `.agent/workflows/sdd-done.md` + `packages/ai-parrot/src/parrot/sdd/_assets/agent/workflows/sdd-done.md`
- `.agents/skills/sdd-done/SKILL.md` + `packages/ai-parrot/src/parrot/sdd/_assets/agents/skills/sdd-done/SKILL.md`

## Codebase Contract
### Verified Imports / Existing Signatures
- `worktree_push_protection._common_config(wt: Path) -> Path`, `_common_values(wt, config, key) -> list[str]`, `disable(wt: Path) -> str`, `main(argv)`.
- `worktree_sync.SyncError(code, message)`, `EXIT_TARGET`.
### Does NOT Exist
- Any helper that edits the common push URL.

## Acceptance Criteria
AC1–AC4 of the spec.

## Validation Commands
```bash
PYTHONPATH=$PWD/packages/ai-parrot/src pytest tests/sdd_scripts/test_worktree_push_protection.py -q
ruff check packages/ai-parrot/src/parrot/sdd/scripts/worktree_push_protection.py tests/sdd_scripts/test_worktree_push_protection.py
```

## Completion Note
_(filled on close)_
