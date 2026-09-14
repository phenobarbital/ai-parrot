# TASK-3237: Worktree structural-hook guard and post-merge install

**Feature**: FEAT-566 — SDD Work Ledger
**Spec**: `sdd/specs/sdd-work-ledger.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3226, TASK-3227
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 10. Linked worktrees must not update structural `wiki.db` from unmerged code; main checkout commits and merges remain indexed.

## Scope

- Update generated hook content to no-op structural `upsert --changed` in linked worktrees through `is_linked_worktree`.
- Extend installer management for `post-merge` without clobbering unrelated hook content.
- Test main/linked hook output and common-dir resolution.

**NOT in scope**: disabling memory-page writes, ledger event emission, root algorithms, or hook cleanup.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py` | MODIFY | Guarded hook content. |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py` | MODIFY | Managed post-merge installation. |
| `tests/knowledge/wiki/test_installer_worktree_guard.py` | CREATE | Hook behavior tests. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
`git_hook_block`, `GIT_HOOK_BEGIN`, and `GIT_HOOK_END` are in `assets.py`; `_git_hook_path` is in `installer.py:619`; `is_linked_worktree` is created by TASK-3227.

### Existing Signatures to Use
`git_hook_block(root: Path) -> str` is at `assets.py:166`. `_git_hook_path(root: Path) -> Path | None` already resolves a linked worktree through its `commondir` pointer.

### Does NOT Exist
- ~~worktree structural-write guard in hook content~~ — this task adds it.
- ~~permission to remove unrelated hook blocks~~ — forbidden.

## Acceptance Criteria

- [ ] Linked hook exits before upsert; main hook retains upsert behavior.
- [ ] Installer uses common hook directory and manages post-merge idempotently.
- [ ] `pytest tests/knowledge/wiki/test_installer_worktree_guard.py -q` passes.

## Test Specification

Use temporary hook files and assert managed/unrelated blocks are retained.

