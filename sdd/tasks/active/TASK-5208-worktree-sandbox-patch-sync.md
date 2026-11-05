# TASK-5208: Add atomic gh-only sandbox patch transport

**Feature**: FEAT-806 — Worktree Sync Base
**Spec**: `sdd/specs/worktree-sync-base.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5207
**Assigned-to**: unassigned

## Context

M1 sandbox transport addresses review issues 1f5e830f5221 and 95434c288bdb: no protected config writes and whole-batch rollback.

## Scope

Implement gh-only download/validation, source-SHA trailers and one ordered git am transaction. Verify host-provisioned protection first, including dry-run. Keep sandbox full-base refusal and all host behavior. NOT in scope: host provisioning automation, relaxing sandbox rules, real-native qualification (TASK-5212).

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py` | MODIFY | Read-only protection checks and batch patch application |
| `tests/sdd_scripts/test_worktree_sync.py` | MODIFY | Patch, failure and rollback regressions |

## Codebase Contract (Anti-Hallucination)

Verified at `cd57902e64`. Dependency-created symbols are explicitly identified below; verify them after dependencies land.

### Verified Imports
```python
import tempfile
import json
import subprocess
from pathlib import Path
from typing import Sequence
import pytest
```
Standard library plus existing pytest. Retain the imports introduced by TASK-5207; do not add provider SDKs or HTTP clients.

### Existing Signatures to Use
- `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py:216`: `_denied_write_paths(root: Path, git_dir: Path) -> list[str]` explicitly protects common config/config.lock and own config.worktree. Read for constraints; do not modify.
- Dependency-created in TASK-5207: `sync`, `main`, `SyncResult`, `SyncError`, `in_sandbox`, `owner_repo`, `check_guards`; signatures are fixed in the parent spec and TASK-5207 blueprint. No current hashes or line numbers can be claimed for these new files; verify after dependency lands.

### Does NOT Exist
- No permission to edit common Git config/config.worktree in sandbox.
- No raw git object download or per-SHA rollback facility; git am --abort covers only its current session.


## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py",
      "action": "MODIFY"
    },
    {
      "path": "tests/sdd_scripts/test_worktree_sync.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py#_denied_write_paths"
  ]
}
```

## Implementation Notes

Extends TASK-5207 worktree_sync.sync/SyncResult and its real-Git test file; serializes both overlapping writers after TASK-5207.

Use repository tools from the activated environment; preserve shared environments. Keep changes within declared files, use typed functions and Google-style docstrings, black (120 columns), and ruff. Tests must import this worktree's source, not another editable checkout. No new dependency is authorized. CLI subprocess I/O is synchronous by design; do not introduce blocking I/O into async entry points. Run no network or destructive operations against the real repository in tests.

## Implementation Blueprint

Blueprint gaps below are planning instructions only; finished code must have no placeholders.

### Steps (in order)

1. Verify dependency anchors after TASK-5207 lands — both modified files are created there.
2. Check extension and effective push URLs without writing config — missing or extra URLs must refuse before transport.
3. Download all metadata and patches to permitted temporary storage outside the target tree; validate non-merge commits and usable mailbox patches — late failures must leave HEAD untouched.
4. Insert the exact source-SHA trailer before the first --- body separator per approved Q1; apply all patches in one git am -3 — preserve request order and traceability.
5. Reuse verified rollback/error reporting and run all existing host tests — sandbox changes must not weaken target/host guards.

### `packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py` (MODIFY)

```python
# Dependency anchor: TASK-5207 creates this exact public signature once.
# Re-read after dependency completion; expected occurrences: 1.
def sync(wt: Path, base: str, *, cherry_picks: Sequence[str] = (), ff_only: bool = False,
         dry_run: bool = False) -> SyncResult:
    """Integrate host commits or one validated sandbox patch batch safely."""
    # FILL IN: retain host implementation; replace sandbox refusal with §2 patch transaction.
# Add private typed helpers for read-only push-protection checks, gh metadata/patch
# download, canonical SHA validation, trailer insertion and a single batched git am.
# Do not introduce a second public entry point or per-SHA am invocations.
```

**Why**: One batch, rather than one session per SHA, provides the promised transaction boundary.

### `tests/sdd_scripts/test_worktree_sync.py` (MODIFY)

```python
# Dependency anchor: test_stale_base_summary from TASK-5207 (expected occurrences: 1).
# Append regression tests using the existing local Git fixtures; preserve host tests.
def test_sandbox_second_patch_conflict_restores_batch(tmp_path: Path) -> None:
    """Second-patch conflict rolls back the first applied patch too."""
    # FILL IN: prepare two gh patches, apply once, assert pre-sync HEAD/index/tree.


def test_sandbox_cherry_pick_via_gh_patch(tmp_path: Path) -> None:
    """Host-configured sandbox applies patches and preserves source-SHA trailers."""
    # FILL IN: PATH gh stub, protected settings, commit messages and no remote changes.
```

**Why**: A second-patch conflict is the regression that single-patch tests miss.


### FILL IN checklist

- [ ] Sandbox never invokes git fetch/pull/push/rebase or config writes; gh api is the only remote transport.
- [ ] Missing extension, absent/extra effective push URLs refuse exit 5 unchanged, also for dry-run; full-base sandbox sync retains host hint.
- [ ] Every requested commit is validated before application; merge commits and bad patches refuse exit 5; later gh failure applies nothing.
- [ ] Applied commit messages include canonical (cherry picked from commit <sha>) trailers, including separator/code-block edge cases from approved Q1.
- [ ] One git am invocation applies the whole ordered batch; second-patch conflict restores pre-sync HEAD/index/tree and clears am state.
- [ ] Abort failure reports status error with actual state/recovery guidance; JSON must not claim restoration falsely.
- [ ] Host behavior and no-push invariants remain passing.

## Acceptance Criteria

- [ ] Sandbox never invokes git fetch/pull/push/rebase or config writes; gh api is the only remote transport.
- [ ] Missing extension, absent/extra effective push URLs refuse exit 5 unchanged, also for dry-run; full-base sandbox sync retains host hint.
- [ ] Every requested commit is validated before application; merge commits and bad patches refuse exit 5; later gh failure applies nothing.
- [ ] Applied commit messages include canonical (cherry picked from commit <sha>) trailers, including separator/code-block edge cases from approved Q1.
- [ ] One git am invocation applies the whole ordered batch; second-patch conflict restores pre-sync HEAD/index/tree and clears am state.
- [ ] Abort failure reports status error with actual state/recovery guidance; JSON must not claim restoration falsely.
- [ ] Host behavior and no-push invariants remain passing.
- [ ] All task validation commands pass and touched Python files pass `ruff check`; apply `black --line-length 120` to touched Python files.

## Validation Commands

- `pytest tests/sdd_scripts/test_worktree_sync.py -q`

## Test Specification

Implement all sandbox rows in spec §4, including trailer insertion, failure of second download/validation, multi-patch conflict, no token/gh failure, empty/bad patch, merge SHA refusal, no-push refs snapshot and no protected config writes. This task uses deterministic gh stubs; native OS qualification belongs to TASK-5212.

## Agent Instructions

1. Use `$sdd-start TASK-5208` in the FEAT-806 feature worktree; never implement on dev.
2. Verify dependencies are done in `sdd/tasks/index/worktree-sync-base.json` and revalidate contracts before editing.
3. Implement only declared files, finish every blueprint gap, and run the listed validation commands. Store logs under `artifacts/logs/`.
4. Commit implementation files, then finalize through `scripts.sdd.finalize_task` using real `TaskCompletionEvidence` and the exact implementation HEAD, following the Codex adaptation contract. Do not manually move tasks or write completion evidence.
5. Commit only the resulting task/index state. Do not push from the worker.

## Completion Note

Pending; populated by the finalization tool after implementation and validation.
