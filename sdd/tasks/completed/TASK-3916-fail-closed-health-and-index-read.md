# TASK-3916: Fail-closed health checks and a broadened worktree-index read

**Feature**: FEAT-619 — worktree_status Tech-Debt Drain (FEAT-582 follow-up)
**Spec**: `sdd/specs/sdd-worktree-status-tech-debt.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3915
**Assigned-to**: unassigned

---

## Context

Implements spec Module 2. Closes two ledger issues from FEAT-582's adversarial
code review:

- `issue:6b0b91e1f5b2` (minor, but the one with real risk) — `_check_health`
  calls `_git("status", "--porcelain", …)` and `_git("log",
  f"origin/{base_branch}..HEAD", …)` and never checks `.returncode` on either.
  When `origin/<base_branch>` does not exist locally (a worktree cut from
  `staging` during a release freeze, or simply an unfetched remote) git writes
  nothing to stdout and exits non-zero, so the code reports
  `dirty_count=0, unpushed_count=0` — i.e. **"clean"**. `ready_for_done` exists
  precisely to stop `/sdd-status` suggesting an unsafe `/sdd-done`, so treating
  *"could not check"* as *"confirmed clean"* turns a safety gate into a
  false green light.
- `issue:8aef2c10c7fd` (minor) — `_read_worktree_index`'s
  `except (FileNotFoundError, json.JSONDecodeError, KeyError)` does not cover
  `PermissionError`, `IsADirectoryError` or `UnicodeDecodeError`, all of which
  `open()`/`json.load()` can raise for a plausible index file. The same
  "never crash the whole scan over one bad worktree" reasoning already
  motivated two CRITICAL fixes in FEAT-582 (commit `2c3efff45`).

Depends on TASK-3915 because both tasks modify
`scripts/sdd/worktree_status.py` and `tests/sdd_scripts/test_worktree_status.py`.

---

## Scope

- Add `dirty_unknown: bool = False` and `unpushed_unknown: bool = False` to
  `WorktreeHealth`.
- Check `.returncode` on both `_git` calls in `_check_health`; on failure leave
  the count at `0` and set the matching `*_unknown` flag.
- Extend the `ready_for_done` conjunction in `discover_worktree_reports` so an
  unknown health signal can never produce `True`.
- Broaden `_read_worktree_index`'s except clause to
  `(OSError, json.JSONDecodeError, UnicodeDecodeError, KeyError)`.
- Write tests for all of the above.

**NOT in scope**:
- Rendering the unknown state in the CLI table — TASK-3917.
- Documenting the unknown flag in the command twins — TASK-3918.
- Non-SDD discovery, ordering, the `flow_type` literal — TASK-3915 (done).
- Any change to `_git`'s "never raises" contract or to `_live_process_count`.
- Retrying or `git fetch`-ing to repair a missing `origin/<base>` ref — this
  module is read-only and must not run a mutating git command.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/worktree_status.py` | MODIFY | `WorktreeHealth` flags, `_check_health` returncode checks, `ready_for_done` gate, `_read_worktree_index` except clause |
| `tests/sdd_scripts/test_worktree_status.py` | MODIFY | Unknown-health and index-read robustness tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from scripts.sdd.worktree_status import (     # verified: tests/sdd_scripts/test_worktree_status.py:13-27
    WorktreeHealth,
    WorktreeReport,
    _check_health,
    _git,
    _read_worktree_index,
    discover_worktree_reports,
)
```

### Existing Signatures to Use

```python
# scripts/sdd/worktree_status.py
class WorktreeHealth(BaseModel):          # line 47
    dirty_count: int = 0                  # line 50
    unpushed_count: int = 0               # line 51
    live_process_count: int = 0           # line 52

def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:   # line 75
    # NEVER raises; a missing cwd is returned as returncode=1 with stderr set.

def _read_worktree_index(wt_path: Path, slug: str) -> tuple[list[WorktreeTaskStatus], str]:  # line 125
    # current except clause (line 138):
    #   except (FileNotFoundError, json.JSONDecodeError, KeyError):
    #       return [], "dev"

def _check_health(wt_path: Path, base_branch: str) -> WorktreeHealth:  # line 190
    status_proc = _git("status", "--porcelain", cwd=wt_path)                      # line 193
    log_proc = _git("log", f"origin/{base_branch}..HEAD", "--oneline", cwd=wt_path)  # line 197
    live_process_count = _live_process_count(wt_path)                             # line 201

# discover_worktree_reports, line 313:
#   ready_for_done = all_done and health.dirty_count == 0 and health.unpushed_count == 0 and index_found
```

```python
# tests/sdd_scripts/test_worktree_status.py
def _completed(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess:  # line 78
class TestHealth:            # line 239  — patches _git with side_effect=[status_proc, log_proc] IN THAT ORDER
class TestReadWorktreeIndex: # line 190
class TestReadyForDone:      # line 294
```

### Does NOT Exist

- ~~`WorktreeHealth.unknown`~~ / ~~`.health_unknown`~~ / ~~`.error`~~ /
  ~~`.stderr`~~ — the two flags are `dirty_unknown` and `unpushed_unknown`,
  exactly those names.
- ~~`_check_health(..., strict=True)`~~ — the signature does not change.
- ~~`subprocess.CalledProcessError` anywhere in this module~~ — `_git` never
  raises and never uses `check=True`.
- ~~`json.JSONDecodeError` being an `OSError`~~ — it is a `ValueError`
  subclass, as is `UnicodeDecodeError`. Neither is covered by `OSError`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "scripts/sdd/worktree_status.py",
      "action": "MODIFY"
    },
    {
      "path": "tests/sdd_scripts/test_worktree_status.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:scripts/sdd/worktree_status.py#WorktreeHealth",
    "sym:scripts/sdd/worktree_status.py#_check_health",
    "sym:scripts/sdd/worktree_status.py#_read_worktree_index",
    "sym:scripts/sdd/worktree_status.py#discover_worktree_reports",
    "sym:scripts/sdd/worktree_status.py#_git"
  ]
}
```

---

## Implementation Notes

### Why two flags and not one

They map to the two distinct git calls, and an operator needs to know *which*
signal is unreadable: a missing `origin/<base_branch>` ref fails only the `log`
call, while a permissions or filesystem problem fails `status`. A single
`health_unknown` would collapse a routine unfetched-remote case and a broken
worktree into the same symbol.

### The counts stay at 0

Do **not** invent a sentinel like `-1` for an unknown count. The flag carries
the uncertainty; the count keeps its type and its meaning ("files I could
actually see"). This is what keeps the pre-existing assertions in
`test_git_missing_worktree_directory_does_not_raise` valid.

### Exception taxonomy

`FileNotFoundError`, `PermissionError` and `IsADirectoryError` are all `OSError`
subclasses, so `OSError` subsumes the current `FileNotFoundError` entry.
`UnicodeDecodeError` is a `ValueError` subclass and must be named separately —
listing `OSError` alone silently leaves it uncaught, which is the exact bug
this task closes.

### Regression you must not cause

`TestHealth::test_git_missing_worktree_directory_does_not_raise` (line ~281)
asserts `dirty_count == 0` and `unpushed_count == 0` for a deleted worktree
directory. Those assertions must keep passing; you ADD `dirty_unknown is True`
and `unpushed_unknown is True` to that test rather than changing what is there.
`_git` returns `returncode=1` for a missing `cwd`, so that path now flows
through the new unknown branch — which is correct and is worth asserting.

---

## Implementation Blueprint

### Steps (in order)

1. Add the two fields to `WorktreeHealth` with `False` defaults — *why*: every
   existing construction site (including tests) keeps working untouched.
2. Capture both `_git` results and branch on `.returncode` — *why*: this is the
   defect; stdout is empty on failure, which is indistinguishable from "clean"
   without the returncode.
3. Extend the `ready_for_done` conjunction — *why*: the flags are decoration
   unless the safety gate actually consumes them; this is the user-visible
   half of `issue:6b0b91e1f5b2`.
4. Broaden the except clause — *why*: one unreadable index must not abort the
   whole scan.
5. Add tests, extend the existing missing-directory test, run the Validation
   Commands — *why*: the suite must only grow.

### `scripts/sdd/worktree_status.py` (MODIFY) — WorktreeHealth flags

```python
# occurrences: 1 (verified: grep -c 'live_process_count: int = 0' scripts/sdd/worktree_status.py)
# AFTER — insert below `    live_process_count: int = 0` (verified: scripts/sdd/worktree_status.py:52)
    #: ``git status`` failed — ``dirty_count`` is not trustworthy. Never report
    #: this worktree as clean (FEAT-619 / issue:6b0b91e1f5b2).
    dirty_unknown: bool = False
    #: ``git log origin/<base>..HEAD`` failed (commonly: the remote-tracking ref
    #: does not exist locally) — ``unpushed_count`` is not trustworthy.
    unpushed_unknown: bool = False
```

**Why this shape**: additive, defaulted, named per git call. Do not rename —
TASK-3917 renders these exact attributes and TASK-3918 documents them.

### `scripts/sdd/worktree_status.py` (MODIFY) — _check_health returncode checks

```python
# occurrences: 1 (verified: grep -c 'live_process_count = _live_process_count(wt_path)' scripts/sdd/worktree_status.py)
# REPLACE the body of `_check_health` from `    # Count dirty files` down to and
# including the closing `    )` of the WorktreeHealth(...) construction
# (verified: scripts/sdd/worktree_status.py:192-207)
    # Count dirty files. A non-zero exit means git could not tell us — stdout is
    # empty in that case, which is indistinguishable from a clean tree, so the
    # count stays 0 and the uncertainty is carried by the flag instead.
    status_proc = _git("status", "--porcelain", cwd=wt_path)
    dirty_unknown = status_proc.returncode != 0
    dirty_count = 0 if dirty_unknown else len([line for line in status_proc.stdout.splitlines() if line.strip()])

    # Count unpushed commits. The common real failure is a missing
    # origin/<base_branch> ref (worktree cut from staging during a freeze, or an
    # unfetched remote) — git exits non-zero and prints nothing.
    log_proc = _git("log", f"origin/{base_branch}..HEAD", "--oneline", cwd=wt_path)
    unpushed_unknown = log_proc.returncode != 0
    unpushed_count = 0 if unpushed_unknown else len([line for line in log_proc.stdout.splitlines() if line.strip()])

    # Count live processes
    live_process_count = _live_process_count(wt_path)

    return WorktreeHealth(
        dirty_count=dirty_count,
        unpushed_count=unpushed_count,
        live_process_count=live_process_count,
        dirty_unknown=dirty_unknown,
        unpushed_unknown=unpushed_unknown,
    )
```

**Why**: the two computations stay structurally identical to each other and to
what was there, so the diff reads as "add a returncode branch" rather than a
rewrite. `_git`'s "never raises" contract is untouched.

### `scripts/sdd/worktree_status.py` (MODIFY) — ready_for_done gate

```python
# occurrences: 1 (verified: grep -c 'ready_for_done = all_done and health.dirty_count == 0' scripts/sdd/worktree_status.py)
# REPLACE the line starting `        ready_for_done = all_done and health.dirty_count == 0`
# (verified: scripts/sdd/worktree_status.py:313)
        # Fail closed: an unreadable health signal must never present as ready.
        # This gate's whole purpose is to avoid suggesting an unsafe /sdd-done.
        ready_for_done = (
            all_done
            and health.dirty_count == 0
            and health.unpushed_count == 0
            and not health.dirty_unknown
            and not health.unpushed_unknown
            and index_found
        )
```

**Why**: the conjunction is now six terms and no longer fits one 120-column
line; the parenthesised form keeps `ruff`/`black` happy and makes each term
individually greppable.

### `scripts/sdd/worktree_status.py` (MODIFY) — broadened except clause

```python
# occurrences: 1 (verified: grep -c 'except (FileNotFoundError, json.JSONDecodeError, KeyError):' scripts/sdd/worktree_status.py)
# REPLACE the line `    except (FileNotFoundError, json.JSONDecodeError, KeyError):` (verified: scripts/sdd/worktree_status.py:138)
    # OSError subsumes FileNotFoundError, PermissionError and IsADirectoryError.
    # UnicodeDecodeError is a ValueError subclass and is NOT covered by OSError,
    # so it must be named explicitly (issue:8aef2c10c7fd).
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, KeyError):
```

### `tests/sdd_scripts/test_worktree_status.py` (MODIFY) — unknown-health tests

```python
# occurrences: 1 (verified: grep -c '    def test_git_missing_worktree_directory_does_not_raise' tests/sdd_scripts/test_worktree_status.py)
# BEFORE — insert above `    def test_git_missing_worktree_directory_does_not_raise`
# as new methods of the existing `class TestHealth` (verified: tests/sdd_scripts/test_worktree_status.py:281)
    def test_health_clean_sets_no_unknown_flags(self):
        """Both git calls succeeding leaves both unknown flags False."""
        # FILL IN: two _completed("") results, assert both *_unknown are False
        #   — bounded by AC5 (guards the default path).
        raise NotImplementedError

    def test_status_failure_marks_dirty_unknown(self):
        """A non-zero `git status` is 'unknown', never 'clean'."""
        # FILL IN: _completed("", returncode=1) for status, _completed("") for log;
        #   assert dirty_unknown is True and dirty_count == 0 — bounded by AC5.
        #   NOTE: TestHealth patches _git with side_effect=[status, log] in that
        #   order — keep that order.
        raise NotImplementedError

    def test_missing_origin_ref_marks_unpushed_unknown(self):
        """A missing origin/<base> ref (git exit 128) is 'unknown'."""
        # FILL IN: _completed("") for status, _completed("", returncode=128) for
        #   log; assert unpushed_unknown is True and unpushed_count == 0
        #   — bounded by AC5.
        raise NotImplementedError
```

```python
# occurrences: 1 (verified: grep -c '        assert health.unpushed_count == 0' tests/sdd_scripts/test_worktree_status.py)
# AFTER — append to the body of `test_git_missing_worktree_directory_does_not_raise`,
# below its final `assert health.unpushed_count == 0` (verified: tests/sdd_scripts/test_worktree_status.py:287)
        # A deleted worktree directory makes _git return returncode=1, so both
        # signals are now explicitly unknown rather than silently "clean".
        assert health.dirty_unknown is True
        assert health.unpushed_unknown is True
```

**Why**: additive assertions on an existing test — the two pre-existing
`== 0` assertions stay exactly as they are (see Implementation Notes).

### `tests/sdd_scripts/test_worktree_status.py` (MODIFY) — ready_for_done gate test

```python
# occurrences: 1 (verified: grep -c '^class TestReadyForDone:' tests/sdd_scripts/test_worktree_status.py)
# AFTER — append as a new method at the end of `class TestReadyForDone`
# (verified: tests/sdd_scripts/test_worktree_status.py:294)
    def test_not_ready_when_health_unknown(self, tmp_path, all_done_index):
        """All tasks done but an unreadable health signal is NOT ready."""
        # FILL IN: drive _discover_with_fake_worktree so the status (or log) git
        #   call returns a non-zero returncode — the existing helper's fake_git
        #   returns _completed(...) with returncode 0, so this needs a variant or
        #   an extra parameter. Assert ready_for_done is False while every task
        #   is "done" — bounded by AC5. This is the regression the ledger issue
        #   is actually about.
        raise NotImplementedError
```

### `tests/sdd_scripts/test_worktree_status.py` (MODIFY) — index-read robustness

```python
# occurrences: 1 (verified: grep -c '^class TestReadWorktreeIndex:' tests/sdd_scripts/test_worktree_status.py)
# AFTER — append as a new method at the end of `class TestReadWorktreeIndex`
# (verified: tests/sdd_scripts/test_worktree_status.py:190)
    @pytest.mark.parametrize(
        "exc",
        [
            PermissionError(13, "Permission denied"),
            IsADirectoryError(21, "Is a directory"),
            UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"),
        ],
        ids=["permission", "is-a-directory", "bad-encoding"],
    )
    def test_unreadable_index_returns_defaults(self, tmp_path, exc):
        """One unreadable index must not propagate out of the scan."""
        # FILL IN: patch builtins.open (or json.load) to raise `exc`, call
        #   _read_worktree_index(tmp_path, "any-slug"), assert it returns
        #   ([], "dev") and raises nothing — bounded by AC6.
        raise NotImplementedError
```

**Why**: parametrized over exactly the three subtypes named in
`issue:8aef2c10c7fd`, so the test fails loudly if the except clause is ever
narrowed back to `FileNotFoundError`.

### FILL IN checklist

- [ ] `TestHealth.test_health_clean_sets_no_unknown_flags` — AC5 default path.
- [ ] `TestHealth.test_status_failure_marks_dirty_unknown` — AC5.
- [ ] `TestHealth.test_missing_origin_ref_marks_unpushed_unknown` — AC5.
- [ ] `TestReadyForDone.test_not_ready_when_health_unknown` — AC5; needs a
      returncode-carrying variant of `_discover_with_fake_worktree`.
- [ ] `TestReadWorktreeIndex.test_unreadable_index_returns_defaults` — AC6.

---

## Acceptance Criteria

- [ ] AC5 — A failed `git status` sets `dirty_unknown`; a failed `git log` sets
      `unpushed_unknown`; neither ever reports as clean, and `ready_for_done` is
      `False` whenever either flag is set.
- [ ] AC6 — `_read_worktree_index` returns `([], "dev")` for `PermissionError`,
      `IsADirectoryError` and `UnicodeDecodeError` without propagating.
- [ ] AC11 — Every pre-existing test in the module still passes, including
      `test_git_missing_worktree_directory_does_not_raise` with its original
      two assertions intact.
- [ ] `ruff check scripts/sdd/worktree_status.py tests/sdd_scripts/test_worktree_status.py`
      is clean.

---

## Validation Commands

- `pytest tests/sdd_scripts/test_worktree_status.py -q`
- `pytest tests/sdd_scripts/test_worktree_status.py::TestHealth -q`
- `pytest tests/sdd_scripts/test_worktree_status.py::TestReadWorktreeIndex -q`
- `pytest tests/sdd_scripts/test_worktree_status.py::TestReadyForDone -q`

---

## Test Specification

See the Implementation Blueprint's test blocks: three new `TestHealth` methods,
one new `TestReadyForDone` method, one parametrized `TestReadWorktreeIndex`
method, plus two additive assertions on the existing missing-directory test.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug sdd-worktree-status-tech-debt --feature-id FEAT-619`)
2. **Read the spec** at `sdd/specs/sdd-worktree-status-tech-debt.spec.md`
3. **Check dependencies** — TASK-3915 must be `"done"` in
   `sdd/tasks/index/sdd-worktree-status-tech-debt.json`. It edits the same two
   files; line numbers in this task's anchors are pre-TASK-3915 and WILL have
   shifted. Re-`grep` every anchor and its occurrence count before editing.
4. **Verify the Codebase Contract** — as above.
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`)
   and commit only that index file.
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`.
7. **Verify** all acceptance criteria — run the Validation Commands.
8. **Commit the code** — stage only the two files this task lists.
9. **Close the task** with
   `scripts/sdd/close_task.sh TASK-3916 sdd-worktree-status-tech-debt verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: Claude Opus 5 (`/sdd-fix issue:07b75dc7dfae`)
**Date**: 2026-10-01
**Notes**: Implemented exactly as blueprinted. Tests: 3 new `TestHealth`
methods, 2 new `TestReadyForDone` methods (the blueprint asked for 1 — split
per git call so a regression names which signal broke), 1 parametrized
`TestReadWorktreeIndex` method over the three exception subtypes, plus the two
additive assertions on `test_git_missing_worktree_directory_does_not_raise`
(its original assertions untouched). Suite: 45 → 53 passing; `ruff check` clean.

The blueprint's FILL IN noted `_discover_with_fake_worktree` could not express
a failing git call. Resolved by giving that pre-existing helper two new
keyword-only parameters, `status_rc=0` / `log_rc=0`, which are backwards
compatible — every existing call site is unchanged.

**Negative control** (to prove the new tests are not vacuous): loaded the
pre-task module from `git show HEAD:scripts/sdd/worktree_status.py` and ran the
new cases against it. `PermissionError`, `IsADirectoryError` and
`UnicodeDecodeError` all PROPAGATED out of `_read_worktree_index`, and
`_check_health` on a missing directory returned
`{dirty_count: 0, unpushed_count: 0, live_process_count: 0}` with no
`dirty_unknown` attribute — i.e. it reported a broken worktree as clean, which
is precisely `issue:6b0b91e1f5b2`.

**Deviations from spec**: none.
