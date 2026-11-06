# TASK-5242: Close the three `--stale` work-loss holes in `remove_worktree`

**Feature**: FEAT-823 — Close the `--stale` work-loss holes in `remove_worktree`
**Spec**: `sdd/specs/scripts-remove-worktree-fixes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:751782605094`
**Discovered-from**: `issue:65a431065cae`

---

## Context

`parrot sdd worktree remove --stale` has three defects that destroy uncommitted
work, all in `packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py`.
This task implements spec Modules 1, 2 and 3 — they all edit that one file and
each depends on the field the previous one adds, so they cannot be split
without serialising three tasks on the same file for no gain.

The three defects (spec §1):

- **D1** (`issue:751782605094`, major) — `discover()` only inspects the top
  level of `.claude/worktrees/`, so a coder *pool* directory is always
  classified a removable orphan even while its `TASK-*-a<N>-<hash>/` children
  are registered git worktrees. `_remove_one()` then `shutil.rmtree`s it
  recursively, and both work-loss gates are no-ops for an orphan.
- **D2** (`issue:65a431065cae`, minor) — `dirty_files()` and `unpushed()` both
  short-circuit on `not self.registered`, so an orphan that is itself a real
  checkout (registration pruned, directory alive) is deleted without `--force`.
- **D3** (`issue:65a431065cae`, minor) — `child.is_dir()` follows symlinks, so a
  symlink is enrolled as an orphan; `shutil.rmtree` raises an uncaught `OSError`
  that aborts the whole sweep part-way through.

---

## Scope

- Add `Worktree.nested_registered: list[Path]` and populate it in `discover()`
  with every registered worktree path found **below** an orphan directory.
- Skip symlinked entries in `discover()` with a warning on stderr.
- Make `dirty_files()` / `unpushed()` evaluate an orphan that is itself a
  checkout, while leaving registered-worktree behaviour byte-for-byte unchanged.
- Add one gate to `_remove_one()`: an orphan holding registered worktrees is
  REFUSED unless `--force`, printing each nested worktree with its own dirty and
  unpushed counts.
- Disclose nested registrations in `cmd_list`'s STATE column, in
  `_remove_one`'s header line, and in the `--dry-run` line.

**NOT in scope**:
- Writing the regression tests — that is TASK-5243.
- Touching the `/remove-worktree` documentation or `_assets/` — that is TASK-5244.
- Any change to the gate chain for **registered** worktrees (primary /
  protected-branch / live-process / dirty / unpushed). AC8 requires it unchanged.
- New CLI flags. `--force` is the only override; do **not** add `--recursive`
  or `--keep-nested`.
- `worktree_status.py`, `/sdd-status`, or the querysource copy of this script.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py` | MODIFY | `nested_registered` field, symlink skip, checkout-aware gates, nested-registration refusal, disclosure |

---

## Codebase Contract (Anti-Hallucination)

Verified against `237cff8aaa` (dev, 2026-11-06).

### Verified Imports

Already at module level (L38-47) — use these, add nothing:

```python
from __future__ import annotations          # line 38
import argparse                             # line 40
from collections.abc import Collection      # line 41
import os                                   # line 42
import subprocess                           # line 43
import sys                                  # line 44
from dataclasses import dataclass, field    # line 45
from pathlib import Path                    # line 46
from typing import Sequence                 # line 47
```

`shutil` is a **function-local** import inside the `else` branch of
`_remove_one` (line 349). Leave it there; do not assume a module-level `shutil`.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py
PROTECTED_BRANCHES = {"main", "dev", "staging", "master"}              # line 50

@dataclass
class Worktree:                                                         # L77-145
    path: Path                                                          # line 87
    branch: str | None                                                  # line 88
    registered: bool                                                    # line 89
    primary: bool = False                                               # line 90
    live_processes: list[tuple[int, str]] = field(default_factory=list)  # line 91

    @property
    def name(self) -> str: ...                                          # L94-95
    def dirty_files(self) -> list[str]: ...                             # L97-102
    def unpushed(self) -> list[str]: ...                                # L104-121
    def pr_state(self) -> str | None: ...                               # L123-145

def _root() -> Path: ...                                                # L63-68
def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess: ...  # L71-73
def discover() -> list[Worktree]: ...                                   # L191-232
def cmd_list(args: argparse.Namespace) -> int: ...                      # L235-266
def _remove_one(wt: Worktree, args: argparse.Namespace) -> int: ...     # L292-364
def cmd_remove(args: argparse.Namespace) -> int: ...                    # L367-404
```

Current bodies of the two methods this task changes:

```python
    def dirty_files(self) -> list[str]:                     # L97
        """Return porcelain status lines, empty when clean."""
        if not self.registered or not self.path.exists():   # L99
            return []
        proc = run(["git", "status", "--porcelain"], cwd=self.path)
        return [ln for ln in proc.stdout.splitlines() if ln.strip()]

    def unpushed(self) -> list[str]:                        # L104
        """..."""
        if not self.registered or not self.path.exists():   # L111
            return []
        upstream = run(["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], cwd=self.path)
        rev = f"{upstream.stdout.strip()}..HEAD" if upstream.returncode == 0 else "origin/dev..HEAD"
        proc = run(["git", "log", "--oneline", rev], cwd=self.path)
        if proc.returncode != 0:
            return []
        return [ln for ln in proc.stdout.splitlines() if ln.strip()]
```

`unpushed()` never reads `self.branch` — only `_remove_one`'s error message
does. A `Worktree` built with `branch=None` can therefore be used to *count*
a nested child's unpushed commits.

### Does NOT Exist

- ~~`Worktree.nested_registered`~~ — **this task adds it**.
- ~~`Worktree._is_checkout`~~ — this task adds it.
- ~~`Worktree.dirty_unknown` / `Worktree.unpushed_unknown`~~ — those belong to
  `worktree_status.py` (the `/sdd-status` panel), **not** this script. Do not
  import or imitate them.
- ~~`remove_worktree.WORKTREE_DIR`~~ — no such constant; the directory is built
  inline as `_root() / ".claude" / "worktrees"` (line 220).
- ~~a module-level `import shutil`~~ — it is function-local at line 349.
- ~~`args.recursive` / `args.keep_nested`~~ — no such flags, and none are added.
- ~~`Path.is_relative_to` being unavailable~~ — it exists (Python ≥ 3.9; this
  repo runs 3.12), use it directly.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py#Worktree",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py#Worktree.dirty_files",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py#Worktree.unpushed",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py#discover",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py#cmd_list",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py#_remove_one"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- **AC8 is a hard constraint**: the gate chain for registered worktrees must
  behave identically. Every change below is additive or scoped to
  `not self.registered`. `test_remove_worktree_refuses_dirty` and
  `test_remove_worktree_list_and_dry_run` must pass untouched.
- **AC7 is the counterweight**: an orphan that is a plain container (no `.git`,
  no nested registrations) must still be swept by `--stale` without `--force`.
  Do not make every orphan refuse — that would break the command's purpose.
- Gate **order** matters: the nested-registration gate goes after the
  live-process gate and before the dirty gate, so a live worker is still
  reported first.
- `--stale` deliberately passes no `--delete-branch`. Do not change that; it is
  what made the 2026-11-06 incident recoverable.

### References in Codebase

- `cmd_remove` selects `--stale` targets at line 372:
  `targets = [w for w in worktrees if not w.registered]`.
- `live_processes_in` (L164-188) already matches process cwds **below** a path,
  so the live-process gate covers nested children; only dirty/unpushed don't.

---

## Implementation Blueprint

### Steps (in order)

1. Add the `nested_registered` field to `Worktree` — *why*: every later change
   reads it, so it must exist first.
2. Add the `_is_checkout()` helper and re-point both gate methods at it —
   *why*: D2 needs "is this a working tree?" instead of "is it registered?".
3. Rewrite the orphan-enrolment loop in `discover()` — *why*: fixes D3 (symlink)
   and supplies D1's facts in one pass over the same lines.
4. Add the nested-registration gate to `_remove_one()` — *why*: this is the
   refusal that actually prevents the D1 data loss.
5. Add the three disclosure points — *why*: AC6; an operator must be able to see
   the hazard in `list` and `--dry-run`, before the refusal.
6. Run `ruff check --fix` on the file and the existing test file — *why*: the
   lint gate blocks the merge tier.

### `packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py` (MODIFY — 1/5: field)

```python
# occurrences: 1 (verified: grep -c 'live_processes: list[tuple[int, str]] = field(default_factory=list)' packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py)
# AFTER — insert below `live_processes: list[tuple[int, str]] = field(default_factory=list)` (verified: packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py:91)
    nested_registered: list[Path] = field(default_factory=list)
```

**Why**: `discover()` needs somewhere to record registered worktrees found below
an orphan, and `_remove_one()` needs to read it. It defaults to an empty list, so
every existing `Worktree(...)` construction site stays valid and no registered
worktree's behaviour changes. Also extend the class docstring's `Attributes:`
block (L80-84) with one line for the new field.

### `packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py` (MODIFY — 2/5: checkout-aware gates)

```python
# occurrences: 2 (verified: grep -c 'if not self.registered or not self.path.exists():' packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py)
# FILL IN: disambiguate — this anchor appears at :99 (inside `dirty_files`) and
# :111 (inside `unpushed`). Quote 2-3 surrounding lines (the preceding docstring
# line of each method) to target each one; BOTH must be replaced with the same
# new guard below.
        if not self.path.exists() or not self._is_checkout():
            return []
```

Add the helper immediately above `dirty_files` (i.e. below the `name` property
at L94-95):

```python
    def _is_checkout(self) -> bool:
        """True when this path is a git working tree, registered or not.

        A registered worktree always is. An orphan directory is only a
        checkout when it still carries a ``.git`` file or directory — a
        deregistered worktree does, a plain container (an emptied coder pool
        directory) does not.
        """
        return self.registered or (self.path / ".git").exists()
```

**Why**: this is the whole of D2. The old guard asked "is git tracking this?",
which is the wrong question — the question is "is there work in here to lose?".
A plain container answers no and stays sweepable (AC7); a deregistered checkout
answers yes and gets real gates (AC4). Registered worktrees are unaffected
because `self.registered` short-circuits first (AC8).

Then make the unregistered case fail **closed** when git cannot answer, in
`dirty_files` only:

```python
        proc = run(["git", "status", "--porcelain"], cwd=self.path)
        # FILL IN: when `proc.returncode != 0` AND `not self.registered`, return a
        # single sentinel line (e.g. "?? (git status failed — state unknown)")
        # rather than []. Bounded by AC4: an orphan checkout whose state cannot be
        # read must NOT be discarded without --force. Leave the registered path
        # exactly as it is today — AC8.
        return [ln for ln in proc.stdout.splitlines() if ln.strip()]
```

### `packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py` (MODIFY — 3/5: discover)

```python
# occurrences: 1 (verified: grep -c 'for child in sorted(worktree_dir.iterdir()):' packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py)
# REPLACE the loop body below `for child in sorted(worktree_dir.iterdir()):` (verified: packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py:222)
    for child in sorted(worktree_dir.iterdir()):
        if child.is_symlink():
            print(
                f"warning: skipping symlinked entry {child.name} under "
                ".claude/worktrees/ (rmtree refuses a symlink).",
                file=sys.stderr,
            )
            continue
        if not child.is_dir():
            continue
        resolved = child.resolve()
        if resolved in registered_paths:
            continue
        nested = sorted(p for p in registered_paths if p != resolved and p.is_relative_to(resolved))
        worktrees.append(
            Worktree(path=child, branch=None, registered=False, nested_registered=nested)
        )
```

**Why**: the `is_symlink()` test must come **before** `is_dir()`, because
`is_dir()` follows symlinks and would swallow the case — that ordering is D3's
entire fix. The `nested` comprehension is D1's: `registered_paths` is already
built from resolved paths at L219, so `is_relative_to` on the resolved child is
a pure set operation with no extra git calls. Excluding `p != resolved` is
redundant today (a registered child would have hit the `continue` above) but
keeps the comprehension correct if the enrolment order ever changes.

### `packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py` (MODIFY — 4/5: the gate)

```python
# occurrences: 1 (verified: grep -c 'if dirty and not args.force:' packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py)
# BEFORE — insert above the `dirty = wt.dirty_files()` / `if dirty and not args.force:` gate (verified: packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py:317)
    if wt.nested_registered:
        label = "WARNING" if args.force else "REFUSED"
        print(
            f"  {label}: holds {len(wt.nested_registered)} registered worktree(s).",
            file=sys.stderr,
        )
        for nested in wt.nested_registered:
            child = Worktree(path=nested, branch=None, registered=True)
            print(
                f"    {nested}  (dirty:{len(child.dirty_files())} "
                f"unpushed:{len(child.unpushed())})",
                file=sys.stderr,
            )
        if not args.force:
            print(
                "  Remove them individually first — they get their own dirty/"
                "unpushed gates — then re-run --stale.",
                file=sys.stderr,
            )
            return 1
```

**Why**: this is the refusal that stops the D1 data loss (AC1). It is placed
after the live-process gate and before the dirty gate so the most urgent reason
is still reported first. Building a throwaway `Worktree(..., registered=True)`
per child is how each one's **own** state is read, which is what AC2 requires —
`unpushed()` does not consult `self.branch`, so `branch=None` is safe here and
its `origin/dev..HEAD` fallback is the right comparison for a never-pushed coder
sub-branch. Under `--force` the loop still runs and still prints, so the
override is informed rather than silent (AC3); only the `return 1` is skipped.

### `packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py` (MODIFY — 5/5: disclosure)

```python
# occurrences: 1 (verified: grep -c 'flags.append("ORPHAN-DIR")' packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py)
# AFTER — insert below `flags.append("ORPHAN-DIR")` (verified: packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py:246)
            if wt.nested_registered:
                flags.append(f"holds:{len(wt.nested_registered)}")
```

```python
# occurrences: 1 (verified: grep -c "(orphan directory, no git record)" packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py)
# REPLACE the line `print(f"  branch: {wt.branch or '(orphan directory, no git record)'}")` (verified: packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py:296)
    if wt.nested_registered:
        orphan_desc = f"(orphan directory, holds {len(wt.nested_registered)} registered worktree(s))"
    else:
        orphan_desc = "(orphan directory, no git record)"
    print(f"  branch: {wt.branch or orphan_desc}")
```

**Why**: AC6. Printing `(orphan directory, no git record)` for a directory that
demonstrably holds git records is the line that cost the operator their last
chance to notice on 2026-11-06. The `holds:N` flag does the same job for `list`.

Finally, extend the `--dry-run` branch (L336-338) to name the nested
registrations:

```python
    if args.dry_run:
        # FILL IN: when wt.nested_registered is non-empty, also print each nested
        # path on its own indented line. Bounded by AC6 — the dry run must
        # disclose them, not just count them.
        print("  [dry-run] would remove this worktree" + (" and delete its branch" if args.delete_branch else ""))
        return 0
```

### FILL IN checklist

- [ ] `dirty_files` / `unpushed` guard — disambiguate the doubled anchor at :99
  and :111 with 2-3 lines of surrounding context each; both get the same guard.
- [ ] `dirty_files` — fail closed on a non-zero `git status` for an
  **unregistered** checkout; bounded by AC4, registered path unchanged per AC8.
- [ ] `--dry-run` branch — list the nested registered paths; bounded by AC6.

---

## Acceptance Criteria

- [ ] `Worktree.nested_registered` exists, defaults to `[]`, and is populated by
  `discover()` for every orphan holding registered worktrees (spec AC1).
- [ ] `--stale` on a directory holding a registered worktree exits non-zero and
  leaves both the directory and the registered child on disk (spec AC1).
- [ ] The refusal names every nested registered worktree with its own dirty and
  unpushed counts (spec AC2).
- [ ] `--stale --force` still prints the nested registrations before removing
  (spec AC3).
- [ ] An orphan directory that is itself a checkout with uncommitted changes or
  unpushed commits is refused without `--force` (spec AC4).
- [ ] A symlink under `.claude/worktrees/` is skipped with a stderr warning, no
  `OSError` escapes, and later orphans are still processed (spec AC5).
- [ ] `list` shows `holds:N` and `_remove_one`'s header says `holds N registered
  worktree(s)` instead of `no git record` (spec AC6).
- [ ] A plain container orphan is still removed by `--stale` without `--force`
  (spec AC7).
- [ ] `pytest packages/ai-parrot/tests/sdd/test_scripts_ledger_worktree.py -q`
  passes — in particular the pre-existing `test_remove_worktree_refuses_dirty`
  and `test_remove_worktree_list_and_dry_run` (spec AC8).
- [ ] `ruff check packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py`
  is clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_scripts_ledger_worktree.py -q`

Run from the worktree with `PYTHONPATH=packages/ai-parrot/src` — the shared
`.venv` is editable-installed against the main checkout, so a bare `pytest`
inside a worktree imports the wrong branch.

---

## Test Specification

This task writes **no** new tests (TASK-5243 does). It must keep the existing
file green:

```python
# packages/ai-parrot/tests/sdd/test_scripts_ledger_worktree.py
def test_remove_worktree_list_and_dry_run(tmp_path, monkeypatch) -> None: ...  # L158
def test_remove_worktree_refuses_dirty(tmp_path, monkeypatch) -> None: ...     # L173
def test_remove_worktree_root_is_primary_checkout(tmp_path, monkeypatch) -> None: ...  # L145
```

Manual smoke check of the D1 path before handing off:

```bash
# in a scratch dir, NOT the repo
git init -q -b feature-x repo && cd repo && git commit -q --allow-empty -m i
mkdir -p .claude/worktrees/feat-FEAT-999-x--pool
git worktree add -q .claude/worktrees/feat-FEAT-999-x--pool/TASK-1-a1 -b t1
PYTHONPATH=<repo>/packages/ai-parrot/src python -m parrot.sdd.scripts.remove_worktree remove --stale --dry-run
# expect: "holds 1 registered worktree(s)" and a non-zero exit, NOT "no git record"
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`parrot sdd worktree ensure --slug scripts-remove-worktree-fixes --feature-id FEAT-823`)
2. **Read the spec** at `sdd/specs/scripts-remove-worktree-fixes.spec.md` (§1 for
   the three mechanisms, §2 for the orphan taxonomy table, §6 for the contract)
3. **Check dependencies** — none.
4. **Verify the Codebase Contract** before writing code: re-run
   `grep -c '<anchor>' packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py`
   for every blueprint anchor. The counts above were taken at `237cff8aaa`; a
   changed count means the anchor moved — re-locate it, do not invent one.
5. **Update status** in `sdd/tasks/index/scripts-remove-worktree-fixes.json` →
   `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the blueprint, completing all three `FILL IN` markers
7. **Verify** every acceptance criterion; run the Validation Command
8. **Commit the code** — stage only
   `packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py`
9. **Close the task** with
   `parrot sdd task close TASK-5242 scripts-remove-worktree-fixes verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
