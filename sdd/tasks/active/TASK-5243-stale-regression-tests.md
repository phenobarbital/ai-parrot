# TASK-5243: Regression tests for the three `--stale` work-loss defects

**Feature**: FEAT-823 — Close the `--stale` work-loss holes in `remove_worktree`
**Spec**: `sdd/specs/scripts-remove-worktree-fixes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5242
**Assigned-to**: unassigned
**Discovered-from**: `issue:751782605094`
**Discovered-from**: `issue:65a431065cae`

---

## Context

TASK-5242 closes three work-loss holes in `--stale`. This task implements spec
Module 4: one regression test per defect, plus the non-regression test that keeps
the sweep useful for its actual purpose.

These tests are the evidence the two ledger issues are really fixed. Without
them the next refactor of `discover()` silently reopens D1, which is the defect
that deleted 15 registered worktrees on 2026-11-06.

---

## Scope

- Add five tests to `packages/ai-parrot/tests/sdd/test_scripts_ledger_worktree.py`:
  one for D1's refusal, one for D1's `--force` disclosure, one for D2, one for
  D3, and one asserting a plain container is still swept.
- Reuse the existing module-level `_git_repo()` harness and the
  `monkeypatch.chdir` + `remove_worktree._ROOT = None` + `remove_worktree.main([...])`
  pattern the file already uses.

**NOT in scope**:
- Changing `remove_worktree.py` — that is TASK-5242. If a test cannot pass
  because the implementation is wrong, report it; do not patch the source here.
- Modifying or deleting the three pre-existing `remove_worktree` tests
  (L145-186). They are AC8's evidence and must keep passing untouched.
- Documentation or `_assets/` — that is TASK-5244.
- A `conftest.py` change. These tests need no new fixture.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/sdd/test_scripts_ledger_worktree.py` | MODIFY | Five new tests inserted above `test_remove_worktree_shim_aliases` |

---

## Codebase Contract (Anti-Hallucination)

Verified against `237cff8aaa` (dev, 2026-11-06).

### Verified Imports

Already at the top of the test file (L3-13) — add nothing:

```python
from __future__ import annotations   # line 3
import importlib                     # line 5
import json                          # line 6
import os                            # line 7
import shutil                        # line 8
import subprocess                    # line 9
import sys                           # line 10
from pathlib import Path             # line 11
import pytest                        # line 13
```

The module under test is imported **inside** each test function, not at module
scope — follow that convention:

```python
from parrot.sdd.scripts import remove_worktree
```

### Existing Signatures to Use

```python
# packages/ai-parrot/tests/sdd/test_scripts_ledger_worktree.py
def _git_repo(path: Path) -> Path:                      # L134-144
    """mkdir + `git init -q -b feature-x` + one empty commit; returns path."""

# The established pattern, from test_remove_worktree_refuses_dirty (L173-186):
#   primary = _git_repo(tmp_path / "repo")
#   worktree = primary / ".claude" / "worktrees" / "wt"
#   worktree.parent.mkdir(parents=True)
#   subprocess.run(["git", "worktree", "add", "-q", str(worktree), "-b", "wt"],
#                  cwd=primary, check=True)
#   monkeypatch.chdir(primary)
#   remove_worktree._ROOT = None
#   assert remove_worktree.main(["remove", "wt"]) != 0
```

```python
# packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py (after TASK-5242)
class Worktree:
    nested_registered: list[Path]            # added by TASK-5242
    def _is_checkout(self) -> bool: ...      # added by TASK-5242
def main(argv: Sequence[str] | None = None) -> int: ...   # L407-434
def discover() -> list[Worktree]: ...                     # L191-232
```

CLI surface these tests drive (verified in `main`, L407-434):
`main(["list"])`, `main(["remove", "<target>"])`, `main(["remove", "--stale"])`,
plus the `--force` and `--dry-run` flags.

### Does NOT Exist

- ~~`remove_worktree._ROOT` being auto-reset between tests~~ — it is a module
  global and **must** be set to `None` manually in each test, exactly as the
  existing tests do (L156, L171, L184). Omitting it leaks the previous test's
  repo root and produces confusing passes.
- ~~a `tmp_repo` / `primary_repo` pytest fixture~~ — none exists in this file;
  build the repo with `_git_repo(tmp_path / "repo")` inline.
- ~~`remove_worktree.main` raising on failure~~ — it **returns** a non-zero exit
  code. Assert on the return value, never with `pytest.raises(SystemExit)`.
- ~~`caplog` capturing the refusals~~ — this script writes to `sys.stderr` with
  `print(..., file=sys.stderr)`, not through `logging`. Use `capsys`.
- ~~`pytest.mark.asyncio`~~ — nothing here is async.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/tests/sdd/test_scripts_ledger_worktree.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/tests/sdd/test_scripts_ledger_worktree.py#_git_repo",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py#main",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py#discover",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py#Worktree"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- `git worktree add` inside `tmp_path` is real git, not a mock — these tests
  already do it, so they are slow but faithful. Keep that; mocking `discover()`
  would not have caught D1.
- A nested-registration fixture needs the child **registered** and the parent
  **not**: create the pool directory with `mkdir`, then
  `git worktree add` the child inside it. That is exactly the shape that broke.
- For D2, make the orphan a real checkout and then deregister it. Deleting the
  registration while keeping the directory is what `git worktree remove`'s
  opposite looks like — use `git worktree add`, then remove only git's
  administrative record (`.git/worktrees/<name>`) and run `git worktree prune`,
  leaving the directory and its `.git` file in place.
- Assert on **filesystem survival**, not only exit codes. A test that checks
  `!= 0` but not `child.is_dir()` would have passed against the old buggy code.

### References in Codebase

- The three existing `remove_worktree` tests: L145-186 of this file.
- `test_installer_stale.py` is about **installer** stale-file detection — a
  different feature despite the name. Do not model these tests on it.

---

## Implementation Blueprint

### Steps (in order)

1. Insert the five tests above `test_remove_worktree_shim_aliases` (L188) —
   *why*: keeps the shim/mount tests last, matching the file's existing shape.
2. Write the D1 refusal test first — *why*: it is the major issue's evidence and
   the hardest fixture; the rest reuse its setup.
3. Add the D1 `--force` disclosure test — *why*: AC3 is about output, so it needs
   `capsys`, unlike the others.
4. Add the D2 and D3 tests — *why*: independent fixtures, no shared state.
5. Add the plain-container non-regression test — *why*: proves the fix did not
   simply disable `--stale` (AC7).
6. Run the Validation Command and `ruff check` on the file.

### `packages/ai-parrot/tests/sdd/test_scripts_ledger_worktree.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c 'def test_remove_worktree_shim_aliases() -> None:' packages/ai-parrot/tests/sdd/test_scripts_ledger_worktree.py)
# BEFORE — insert above `def test_remove_worktree_shim_aliases() -> None:` (verified: packages/ai-parrot/tests/sdd/test_scripts_ledger_worktree.py:188)
def _pool_with_registered_child(primary: Path, pool_name: str = "feat-FEAT-999-x--pool") -> tuple[Path, Path]:
    """Build an unregistered pool dir holding one registered worktree.

    Returns ``(pool, child)``. This is the FEAT-823 D1 shape: the pool itself is
    never a git worktree, only the ``TASK-*`` child inside it is.
    """
    pool = primary / ".claude" / "worktrees" / pool_name
    pool.mkdir(parents=True)
    child = pool / "TASK-1-a1"
    subprocess.run(
        ["git", "worktree", "add", "-q", str(child), "-b", "task-1-a1"],
        cwd=primary,
        check=True,
    )
    return pool, child


def test_stale_refuses_orphan_holding_registered_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # FEAT-823 AC1 / issue:751782605094
    """--stale must not rmtree a pool dir that still holds a registered worktree."""
    from parrot.sdd.scripts import remove_worktree

    primary = _git_repo(tmp_path / "repo")
    pool, child = _pool_with_registered_child(primary)
    monkeypatch.chdir(primary)
    remove_worktree._ROOT = None

    assert remove_worktree.main(["remove", "--stale"]) != 0
    assert pool.is_dir(), "pool dir was deleted despite holding a registered worktree"
    assert child.is_dir(), "registered child was deleted"
    # FILL IN: also assert the child is STILL registered — parse
    # `git worktree list --porcelain` in `primary` and look for the child path.
    # Bounded by AC1: survival on disk is not enough if git's record is gone.


def test_stale_force_reports_nested_registrations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:  # FEAT-823 AC2 + AC3
    """--force removes the pool but still names every nested worktree first."""
    from parrot.sdd.scripts import remove_worktree

    primary = _git_repo(tmp_path / "repo")
    pool, child = _pool_with_registered_child(primary)
    monkeypatch.chdir(primary)
    remove_worktree._ROOT = None

    remove_worktree.main(["remove", "--stale", "--force"])
    err = capsys.readouterr().err
    assert "TASK-1-a1" in err, "the nested worktree was not named before removal"
    # FILL IN: assert the per-child dirty/unpushed counts appear too (AC2) —
    # match on the "dirty:" and "unpushed:" tokens, not on exact numbers, since
    # a fresh `git worktree add` has 0 of each. Bounded by AC2.


def test_stale_refuses_dirty_orphan_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # FEAT-823 AC4 / issue:65a431065cae
    """A deregistered-but-live checkout with uncommitted work is gated."""
    from parrot.sdd.scripts import remove_worktree

    primary = _git_repo(tmp_path / "repo")
    orphan = primary / ".claude" / "worktrees" / "wt"
    orphan.parent.mkdir(parents=True)
    subprocess.run(["git", "worktree", "add", "-q", str(orphan), "-b", "wt"], cwd=primary, check=True)
    (orphan / "dirty.txt").write_text("uncommitted\n")
    # FILL IN: deregister it while keeping the directory and its `.git` file —
    # remove `.git/worktrees/wt` under the primary checkout, then
    # `git worktree prune`. Verify with `git worktree list --porcelain` that the
    # path is gone from git's records but `orphan / ".git"` still exists.
    # Bounded by AC4: the test is meaningless unless the orphan really is
    # unregistered AND really is a checkout.
    monkeypatch.chdir(primary)
    remove_worktree._ROOT = None

    assert remove_worktree.main(["remove", "--stale"]) != 0
    assert (orphan / "dirty.txt").exists()
    assert remove_worktree.main(["remove", "--stale", "--force"]) == 0
    assert not orphan.exists()


def test_stale_skips_symlinked_orphan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # FEAT-823 AC5 / issue:65a431065cae
    """A symlink is skipped with a warning; the sweep still completes."""
    from parrot.sdd.scripts import remove_worktree

    primary = _git_repo(tmp_path / "repo")
    worktrees = primary / ".claude" / "worktrees"
    worktrees.mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    link = worktrees / "aaa-link"
    link.symlink_to(elsewhere, target_is_directory=True)
    plain = worktrees / "zzz-plain"
    plain.mkdir()
    monkeypatch.chdir(primary)
    remove_worktree._ROOT = None

    # Sorted enumeration puts the symlink first, so an OSError here would abort
    # before `zzz-plain` is reached — that is exactly the D3 regression.
    assert remove_worktree.main(["remove", "--stale"]) == 0
    assert link.is_symlink(), "the symlink itself must be left alone"
    assert elsewhere.is_dir(), "the symlink target must never be touched"
    assert not plain.exists(), "the sweep stopped early instead of continuing"


def test_stale_still_removes_plain_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # FEAT-823 AC7 — non-regression
    """An emptied pool dir is still swept without --force."""
    from parrot.sdd.scripts import remove_worktree

    primary = _git_repo(tmp_path / "repo")
    pool = primary / ".claude" / "worktrees" / "feat-FEAT-998-y--pool"
    pool.mkdir(parents=True)
    (pool / "leftover.log").write_text("scratch\n")
    monkeypatch.chdir(primary)
    remove_worktree._ROOT = None

    assert remove_worktree.main(["remove", "--stale"]) == 0
    assert not pool.exists()
```

**Why this shape**: every test asserts the **filesystem outcome**, not just the
exit code, because the old code returned 0 and deleted the tree — an exit-code-only
assertion would have passed against the bug. `_pool_with_registered_child` is a
module-level helper rather than a fixture to match the file's existing
`_git_repo` convention. In `test_stale_skips_symlinked_orphan` the names
`aaa-link` / `zzz-plain` are deliberate: `discover()` iterates
`sorted(worktree_dir.iterdir())`, so the symlink is visited first and a raised
`OSError` would leave `zzz-plain` untouched — the final assertion is what proves
the sweep did not abort.

### FILL IN checklist

- [ ] `test_stale_refuses_orphan_holding_registered_worktree` — assert the child
  is still in `git worktree list --porcelain`; bounded by AC1.
- [ ] `test_stale_force_reports_nested_registrations` — assert the `dirty:` /
  `unpushed:` tokens appear per child; bounded by AC2.
- [ ] `test_stale_refuses_dirty_orphan_checkout` — deregister the worktree while
  keeping the directory and its `.git`; bounded by AC4.

---

## Acceptance Criteria

- [ ] Five new tests exist, named as in the blueprint, each carrying the
  FEAT-823 AC and issue id it covers in a comment.
- [ ] All five pass against TASK-5242's implementation.
- [ ] Each of the three defects is covered by a test that **fails** against the
  pre-TASK-5242 code — verify by stashing TASK-5242's change, or by reasoning
  explicitly in the Completion Note about why each would have failed.
- [ ] The three pre-existing `remove_worktree` tests (L145-186) are unmodified
  and still pass (spec AC8).
- [ ] No new fixtures in a `conftest.py`; no network, no real repo mutation
  outside `tmp_path`.
- [ ] `ruff check packages/ai-parrot/tests/sdd/test_scripts_ledger_worktree.py`
  is clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_scripts_ledger_worktree.py -q`

Run from the worktree with `PYTHONPATH=packages/ai-parrot/src` — the shared
`.venv` is editable-installed against the main checkout, so a bare `pytest`
inside a worktree imports the wrong branch.

---

## Test Specification

The five tests above **are** this task's deliverable. Expected final state of
the file's `remove_worktree` section:

```python
def _git_repo(path: Path) -> Path: ...                                  # existing, L134
def test_remove_worktree_root_is_primary_checkout(...) -> None: ...     # existing, L145
def test_remove_worktree_list_and_dry_run(...) -> None: ...             # existing, L158
def test_remove_worktree_refuses_dirty(...) -> None: ...                # existing, L173
def _pool_with_registered_child(...) -> tuple[Path, Path]: ...          # new
def test_stale_refuses_orphan_holding_registered_worktree(...) -> None: ...  # new
def test_stale_force_reports_nested_registrations(...) -> None: ...     # new
def test_stale_refuses_dirty_orphan_checkout(...) -> None: ...          # new
def test_stale_skips_symlinked_orphan(...) -> None: ...                 # new
def test_stale_still_removes_plain_container(...) -> None: ...          # new
def test_remove_worktree_shim_aliases() -> None: ...                    # existing, L188
def test_worktree_verbs_mounted() -> None: ...                          # existing, L197
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`parrot sdd worktree ensure --slug scripts-remove-worktree-fixes --feature-id FEAT-823`)
2. **Read the spec** at `sdd/specs/scripts-remove-worktree-fixes.spec.md` (§4 for
   the test table, §2 for the orphan taxonomy each test pins down)
3. **Check dependencies** — TASK-5242 must be `"done"` in
   `sdd/tasks/index/scripts-remove-worktree-fixes.json`
4. **Verify the Codebase Contract** — confirm `Worktree.nested_registered` and
   `_is_checkout` really landed in TASK-5242 before writing tests against them
5. **Update status** in `sdd/tasks/index/scripts-remove-worktree-fixes.json` →
   `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the blueprint, completing all three `FILL IN` markers
7. **Verify** every acceptance criterion; run the Validation Command
8. **Commit the code** — stage only
   `packages/ai-parrot/tests/sdd/test_scripts_ledger_worktree.py`
9. **Close the task** with
   `parrot sdd task close TASK-5243 scripts-remove-worktree-fixes verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.
Include the per-defect reasoning required by AC3 above.

**Deviations from spec**: none | describe if any
