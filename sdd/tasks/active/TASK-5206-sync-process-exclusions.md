# TASK-5206: Add explicit PID exclusions to worktree process detection

**Feature**: FEAT-806 — Worktree Sync Base
**Spec**: `sdd/specs/worktree-sync-base.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

## Context

M2 enables an in-worktree sync caller to exclude its ancestry without weakening list/remove defaults.

## Scope

Add Collection[int] exclude_pids with default (). Preserve own-PID exclusion and cwd/descendant matching. Correct the existing misleading parent-skipping docstring. Do not automatically exclude parents for existing callers. NOT in scope: ancestry traversal, target resolution, transport or removal behavior changes.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py` | MODIFY | Backward-compatible exclusion parameter |
| `tests/sdd_scripts/test_sync_process_exclusions.py` | CREATE | Process guard regressions |

## Codebase Contract (Anti-Hallucination)

Verified at `cd57902e64`. Dependency-created symbols are explicitly identified below; verify them after dependencies land.

### Verified Imports
```python
from collections.abc import Collection
from pathlib import Path
import os
import pytest
from parrot.sdd.scripts import remove_worktree
```
Collection/pathlib/os are standard library; pytest is in root pyproject.toml. remove_worktree.py:163 defines `live_processes_in(path: Path) -> list[tuple[int, str]]`; `_proc_cwd(pid: int) -> Path | None` at :146 and `_proc_cmdline(pid: int) -> str` at :154 provide the current seams.

### Existing Signatures to Use
`live_processes_in`, `_proc_cwd`, `_proc_cmdline` retain their behavior except the explicit exclusion set. `discover()` at :191 calls `live_processes_in(wt.path)` without exclusions.

### Does NOT Exist
- No `exclude_pids` argument today.
- Automatic parent exclusion is only claimed in the docstring, not implemented.


## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py",
      "action": "MODIFY"
    },
    {
      "path": "tests/sdd_scripts/test_sync_process_exclusions.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py#live_processes_in",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py#_proc_cwd",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py#_proc_cmdline",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py#discover"
  ]
}
```

## Implementation Notes

Independent M2: edits only remove_worktree.py and its new focused tests; no shared external resources.

Use repository tools from the activated environment; preserve shared environments. Keep changes within declared files, use typed functions and Google-style docstrings, black (120 columns), and ruff. Tests must import this worktree's source, not another editable checkout. No new dependency is authorized. CLI subprocess I/O is synchronous by design; do not introduce blocking I/O into async entry points. Run no network or destructive operations against the real repository in tests.

## Implementation Blueprint

Blueprint gaps below are planning instructions only; finished code must have no placeholders.

### Steps (in order)

1. Verify the old scanner and callers — defaults must remain unchanged.
2. Add the keyword and correct its documentation — ancestry is caller-owned.
3. Test explicit and default PID sets — prove a foreign worker still blocks.

### `packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py` (MODIFY)

Anchor `def live_processes_in(path: Path) -> list[tuple[int, str]]:` — packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py:163, occurrences: 1 (verified at cd57902e64).

```python
# Add `from collections.abc import Collection` with existing imports.
def live_processes_in(path: Path, exclude_pids: Collection[int] = ()) -> list[tuple[int, str]]:
    """Return live cwd matches, skipping own PID and explicitly excluded PIDs."""
    # FILL IN: preserve current scanning and errors; skip pid in exclude_pids.
```

**Why**: Explicit exclusions preserve remove/list safety defaults.

### `tests/sdd_scripts/test_sync_process_exclusions.py` (CREATE)

```python
"""Regression tests for explicit worktree PID exclusions."""
from pathlib import Path
import os
import pytest
from parrot.sdd.scripts import remove_worktree


def test_default_keeps_foreign_and_parent_processes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Default callers retain foreign cwd matches and omit only self."""
    # FILL IN: script proc entries and _proc_cwd; assert exact returned PID list.


def test_explicit_exclusions_preserve_other_matches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Excluded ancestors disappear without hiding a sibling worker."""
    # FILL IN: include self, excluded ancestor, descendant worker, unrelated cwd and unreadable cwd.
```

**Why**: Mock /proc enumeration rather than relying on unrelated host processes.


### FILL IN checklist

- [ ] Default calls preserve matching foreign and parent processes while ignoring self.
- [ ] Explicit exclusions accept a Collection and do not mutate it; unrelated and unreadable cwd entries retain prior handling.

## Acceptance Criteria

- [ ] Default calls preserve matching foreign and parent processes while ignoring self.
- [ ] Explicit exclusions accept a Collection and do not mutate it; unrelated and unreadable cwd entries retain prior handling.
- [ ] All task validation commands pass and touched Python files pass `ruff check`; apply `black --line-length 120` to touched Python files.

## Validation Commands

- `pytest tests/sdd_scripts/test_sync_process_exclusions.py -q`

## Test Specification

Cover default empty exclusions, multiple excluded PIDs, descendant cwd, similarly prefixed unrelated directories, unreadable cwd and self exclusion.

## Agent Instructions

1. Use `$sdd-start TASK-5206` in the FEAT-806 feature worktree; never implement on dev.
2. Verify dependencies are done in `sdd/tasks/index/worktree-sync-base.json` and revalidate contracts before editing.
3. Implement only declared files, finish every blueprint gap, and run the listed validation commands. Store logs under `artifacts/logs/`.
4. Commit implementation files, then finalize through `scripts.sdd.finalize_task` using real `TaskCompletionEvidence` and the exact implementation HEAD, following the Codex adaptation contract. Do not manually move tasks or write completion evidence.
5. Commit only the resulting task/index state. Do not push from the worker.

## Completion Note

Pending; populated by the finalization tool after implementation and validation.
