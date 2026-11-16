# TASK-5705: Close `/sdd-brief` tasks in place with `parrot sdd task close`

**Feature**: FEAT-901 — `parrot sdd task close` closes `/sdd-brief` tasks in place
**Spec**: `sdd/specs/scripts-close-task-fixes.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:2693ab44132d`

---

## Context

Spec §2 / §3 Module 1. `close_task.main` only knows `sdd/tasks/active|completed/` and
`sdd/tasks/index/<slug>.json`, so `parrot sdd task close HOTFIX-<KEY>-<N> <slug>` exits 2 for a brief task
(`sdd/briefs/<slug>/tasks/…`, index `sdd/briefs/<slug>.index.json`). Briefs close in place: no move.

---

## Scope

- Add `BRIEFS_DIR` and the private function `_close_brief_task` to `close_task.py`.
- Dispatch to it from `main` when the slug has a brief index and no feature index.
- Describe the brief mode in the module docstring.
- Tests: a `brief_repo` fixture and the six tests listed in spec §4.

**NOT in scope**: `finalize_task.py`, `heal_orphans.py`, `cli.py` help text, the `jq` recipe in
`sdd-worker` / `/sdd-brief` / `/sdd-done` and their twins, the Completion Note, any new CLI argument.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/close_task.py` | MODIFY | `BRIEFS_DIR`, `_close_brief_task`, dispatch in `main`, docstring |
| `packages/ai-parrot/tests/sdd/test_scripts_shell_port.py` | MODIFY | `brief_repo` fixture and six tests |

---

## Codebase Contract (Anti-Hallucination)

Verified against `b3dd3ba3b7`.

### Verified Imports
```python
# packages/ai-parrot/src/parrot/sdd/scripts/close_task.py — already imported at the top of the file
import json        # line 13
import subprocess  # line 17
import sys         # line 18
from collections.abc import Sequence  # line 20
from pathlib import Path              # line 22
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/sdd/scripts/close_task.py
INDEX_DIR = "sdd/tasks/index"  # line 26
def _git(args: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]  # line 30
def _out(line: str) -> None  # line 35
def _err(line: str) -> None  # line 39
def sync_status_header(task_file: Path) -> bool  # line 51
def update_index(index: Path, task_id: str, verification: str, completed_file: str, now: str) -> None  # line 65
def _emit_task_closed(start_dir: Path, task_id: str, feature_slug: str, verification: str) -> None  # line 97
def main(argv: Sequence[str] | None = None) -> int  # line 147 — :168 `index = repo_root / index_rel`

# packages/ai-parrot/tests/sdd/test_scripts_shell_port.py
def _git(repo: Path, *args: str) -> str  # line 18
def repo(tmp_path: Path) -> Path  # fixture, line 23
def _module(name: str, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]  # line 45
def _wrapper(name: str, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]  # line 50
```

### Does NOT Exist
- ~~`close_task.BRIEFS_DIR`, `close_task._close_brief_task`~~ — created by this task.
- ~~a `--brief` flag~~ — detection is by index file.
- ~~a `completed/` directory for briefs~~ — the task file never moves.
- ~~`brief_repo` fixture~~ — created by this task.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/sdd/scripts/close_task.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/sdd/test_scripts_shell_port.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/close_task.py#main",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/close_task.py#update_index",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/close_task.py#sync_status_header"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The feature path keeps its output and exit codes. The dispatch runs before `completed_dir.mkdir(...)`, so
  brief mode never creates `sdd/tasks/completed/`.
- A feature index wins when both indexes exist for the slug.
- `update_index` silently ignores an unknown id: look the entry up first and return 2.
- The recorded `file` must resolve inside `repo_root` and be a file, else return 2.
- No `"jq"` and no `"bash"` string literals in the module (`test_ports_do_not_shell_out_to_jq_or_bash`).

---

## Implementation Blueprint

### `close_task.py`

After `INDEX_DIR = "sdd/tasks/index"`:

```python
BRIEFS_DIR = "sdd/briefs"
```

Before `def main(`:

```python
def _close_brief_task(
    repo_root: Path, index_rel: str, task_id: str, feature_slug: str, verification: str, now: str
) -> int:
    """Close a ``/sdd-brief`` task in place: header, per-brief index entry and staging, with no file move.

    Args:
        repo_root: Resolved top level of the checkout.
        index_rel: Repo-relative path of the per-brief index (``sdd/briefs/<slug>.index.json``).
        task_id: Brief task id (``HOTFIX-<KEY>-<N>``).
        feature_slug: Brief slug.
        verification: Verification label recorded on the index entry.
        now: Timestamp used for ``completed_at``.

    Returns:
        0 closed (idempotent), 2 unknown id or missing task file, 5 invalid index, or a failing ``git add`` code.
    """
    index = repo_root / index_rel
    try:
        data = json.loads(index.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        _err(f"jq: error: invalid index JSON: {exc}")
        return 5
    tasks = data.get("tasks") if isinstance(data, dict) else None
    if not isinstance(tasks, list) or not all(isinstance(t, dict) for t in tasks):
        _err("jq: error: index has no iterable task list")
        return 5
    entry = next((t for t in tasks if t.get("id") == task_id), None)
    if entry is None:
        _err(f"✗ {task_id}: not in {index_rel}.")
        return 2
    file_rel = entry.get("file")
    task_file = (repo_root / file_rel).resolve() if isinstance(file_rel, str) and file_rel else None
    if task_file is None or not task_file.is_relative_to(repo_root) or not task_file.is_file():
        _err(f"✗ {task_id}: task file not found: {file_rel}")
        return 2
    if sync_status_header(task_file):
        _out(f"✓ {task_id}: header **Status** → done")
    try:
        update_index(index, task_id, verification, file_rel, now)
    except ValueError as exc:
        _err(f"jq: error: {exc}")
        return 5
    added = _git(["add", "--", index_rel, file_rel], repo_root)
    if added.returncode != 0:
        sys.stderr.write(added.stderr)
        return added.returncode
    _out(f"✅ {task_id} closed in place (verification={verification}).")
    _emit_task_closed(repo_root, task_id, feature_slug, verification)
    return 0
```

In `main`, right after `index = repo_root / index_rel`:

```python
    brief_index_rel = f"{BRIEFS_DIR}/{feature_slug}.index.json"
    if not index.is_file() and (repo_root / brief_index_rel).is_file():
        return _close_brief_task(repo_root, brief_index_rel, task_id, feature_slug, verification, now)
```

Module docstring: add a paragraph stating that a slug with `sdd/briefs/<slug>.index.json` and no feature index
is a brief, closed in place (header, index entry, staging, no move), and that exit 2 also covers an id absent
from the brief index or a missing task file.

### `test_scripts_shell_port.py`

A `brief_repo` fixture (spec §4 "Test Data / Fixtures") and the tests
`test_close_brief_task_in_place` (parametrized over `_module` / `_wrapper`),
`test_close_brief_task_is_idempotent`, `test_close_brief_task_unknown_id_exits_2`,
`test_close_brief_task_missing_file_exits_2`, `test_close_brief_invalid_index_exits_5` and
`test_feature_index_wins_over_brief_index`, inserted before `test_ports_do_not_shell_out_to_jq_or_bash`.
Spec §4 states what each asserts.

---

## Acceptance Criteria

- [ ] A brief task closes in place with exit 0: header `done`, index entry `done` with `completed_at` and
      `verification`, top-level `completed_at`, both files staged, no `sdd/tasks/completed/` created.
- [ ] A second run exits 0 and keeps `completed_at` and `verification`.
- [ ] Unknown id, missing task file and a task file outside the repository exit 2; an invalid brief index exits 5.
- [ ] A feature index wins over a brief index with the same slug.
- [ ] Every pre-existing test in `test_scripts_shell_port.py` still passes.
- [ ] `ruff check` is clean on both files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_scripts_shell_port.py -q`

---

## Test Specification

Spec §4 rows 1–6 state what each new test asserts.

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug scripts-close-task-fixes --feature-id FEAT-901`).
2. Verify the Codebase Contract, mark the task `in-progress` in `sdd/tasks/index/scripts-close-task-fixes.json`.
3. Implement from the blueprint, run the Validation Commands from the worktree root.
4. Commit only the two files listed, close with the close script, fill in the Completion Note.

---

## Completion Note

**Completed by**: Claude Code (`/sdd-fix` session, actor `agent:sdd-fix:ae77dc9c`)
**Date**: 2026-11-16
**Notes**: `close_task.main` dispatches to the new `_close_brief_task` when the slug has
`sdd/briefs/<slug>.index.json` and no per-spec index. The brief task is closed in place: header, index entry
(`status`, write-once `completed_at` / `verification`), top-level `completed_at`, staging of both files and the
`task.closed` event. Code commit `dc3327fb89`. Validation:
`pytest packages/ai-parrot/tests/sdd/test_scripts_shell_port.py` → 18 passed; with `close_task.py` reverted to
`origin/dev` the same file gives 8 failed, 10 passed. `ruff check` is clean on both files.

**Deviations from spec**: none. `test_close_brief_task_missing_file_exits_2` is parametrized over three recorded
`file` values (missing file, path outside the repository, `null`). Both files were already not `black`-conformant
on `origin/dev`; they were not reformatted here.
