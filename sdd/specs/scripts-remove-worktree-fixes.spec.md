---
type: feature
base_branch: dev
projects: [ai-parrot, sdd-tooling]
tags: [sdd-tooling, worktree, remove-worktree, data-loss, ledger-fix]
---

# Feature Specification: Close the `--stale` work-loss holes in `remove_worktree`

**Feature ID**: FEAT-823
**Date**: 2026-11-06
**Author**: /sdd-fix (agent:sdd-fix:118971f4)
**Status**: approved
**Target version**: 2.1.2

---

## 1. Motivation & Business Requirements

### Problem Statement

`parrot sdd worktree remove --stale` presents itself as the safe bulk sweep: an
"orphan directory" has no git record, so removing it is advertised as a plain
directory delete. The gate table in `/remove-worktree` promises that `--force`
is required before anything uncommitted is discarded.

For orphan directories that promise does not hold. Two claimed ledger issues on
`packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py` describe three
distinct defects in the same code path.

#### D1 — nested registered worktrees are deleted as "orphans" (`issue:751782605094`, major)

`discover()` (L191-232) scans only the **top level** of `.claude/worktrees/`
and classifies a child as an orphan when `child.resolve() not in
registered_paths`. A coder *pool* directory (`feat-FEAT-<NNN>-<slug>--pool/`) is
never itself a registered worktree — only its `TASK-*-a<N>-<hash>/` children
are — so a pool dir is **always** classified a removable orphan. The membership
test examines the child only, never its descendants.

`_remove_one()` then reaches the `else` branch at L348-352 and calls
`shutil.rmtree(wt.path)`, which is unconditional and recursive. Every nested
registered worktree is destroyed along with it.

Observed 2026-11-06 during a 137-worktree cleanup: `--stale --dry-run` listed
all 4 pool dirs (FEAT-584, FEAT-704, FEAT-721, FEAT-752) as removable orphans
while they held **15 registered worktrees, 7 of them dirty**, and reported each
as `branch: (orphan directory, no git record)`. `--stale --force` then deleted
all 4 recursively.

Blast radius was limited by luck, not design. Git stayed consistent (`git
worktree prune` runs at L356 and in `cmd_remove`, 0 prunable afterwards) and all
51 `--TASK-*` branches survived with their commits, because `--stale` passes no
`--delete-branch`. Committed work was therefore recoverable; the loss is
confined to **uncommitted** state in the children. In that incident the 7 dirty
trees had been backed up and every file verified already present on
`origin/dev` first — operator caution, not a guarantee the tool offers.

#### D2 — orphan directories bypass the dirty and unpushed gates entirely (`issue:65a431065cae`, minor)

`Worktree.dirty_files()` (L97-102) and `Worktree.unpushed()` (L104-121) both
open with:

```python
if not self.registered or not self.path.exists():
    return []
```

For any orphan both gates in `_remove_one()` (L316-333) are therefore
**hard-coded no-ops by construction**, not empty-by-accident. An orphan
directory that is itself a real checkout — a worktree whose registration was
pruned while the directory survived — holds genuinely unpushed commits and
uncommitted edits, and `--stale` deletes it with no refusal and without
`--force`.

#### D3 — a symlinked orphan aborts the sweep with an uncaught `OSError` (`issue:65a431065cae`, minor)

`discover()` filters with `child.is_dir()`, which **follows symlinks**, so a
symlink pointing at a directory is enrolled as an orphan. `shutil.rmtree`
refuses a symlink and raises `OSError`, which nothing catches — the exception
escapes `_remove_one()` and aborts the whole `--stale` sweep part-way through,
after earlier targets have already been deleted.

### Why it matters

Pool directories are the normal residue of **any** `sdd-worker` run, so D1 is
reachable in routine cleanup rather than in an exotic state. D2 and D3 make the
same command unsafe and non-atomic for the other two orphan shapes. The dry run
discloses none of it, which removes the operator's last chance to notice.

### Goals

- G1 — `--stale` MUST NOT delete a directory that contains a registered git
  worktree, with or without `--force`, unless the operator is first shown
  exactly which registrations it holds and what each would lose.
- G2 — The dirty and unpushed gates MUST be evaluated for an orphan directory
  that is itself a checkout, so `--force` is required before discarding its
  uncommitted or unpushed work.
- G3 — A symlinked entry under `.claude/worktrees/` MUST be skipped with a
  warning instead of aborting the sweep.
- G4 — `list` and `--dry-run` MUST disclose nested registrations instead of
  printing `(orphan directory, no git record)` for a directory that
  demonstrably holds git records.
- G5 — The `/remove-worktree` documentation MUST describe the real gate
  semantics, in all copies the installer ships.

### Non-Goals (explicitly out of scope)

- Changing the gate semantics for **registered** worktrees — the
  primary/protected-branch/live-process/dirty/unpushed chain at L298-333 is
  correct and stays as-is.
- Making `--stale` delete branches, or changing anything about
  `--delete-branch`. `--stale` passing no `--delete-branch` is precisely what
  made the observed incident recoverable.
- `parrot sdd worktree status` / `worktree_status.py` reconciliation, and the
  `/sdd-status` worktree panel.
- The sibling copy of this script in the **querysource** repo
  (`scripts/remove_worktree.py`), which has the same defects. Different repo,
  out of this feature's reach.
- Automatic recovery or backup of discarded work. The gates refuse; they do not
  archive.

---

## 2. Architectural Design

### Overview

Keep the existing gate chain and add the missing *facts* to the `Worktree`
record so the chain can act on them. Three narrow changes, all in
`remove_worktree.py`:

1. `discover()` learns to look **below** each top-level child and attaches any
   registered worktree paths it finds to the orphan's record; it also skips
   symlinks.
2. `_remove_one()` gains one new gate for an orphan that holds registrations,
   placed next to the existing work-loss gates, which reports each nested
   worktree's own dirty/unpushed state before `--force` may override.
3. `dirty_files()` / `unpushed()` stop short-circuiting on `not registered` and
   instead short-circuit on "this directory is not a checkout at all", so a
   deregistered-but-live checkout gets real gates.

```
discover()
  ├─ child.is_symlink()            → skip + warn           (D3)
  ├─ child.resolve() in registered → registered Worktree   (unchanged)
  └─ orphan Worktree
       └─ nested_registered = [p for p in registered_paths
                                 if p.is_relative_to(child.resolve())]   (D1)

_remove_one(wt)
  ├─ primary / protected / live_processes      (unchanged)
  ├─ NEW: wt.nested_registered and not --force → REFUSE, naming each child
  │        and its own dirty/unpushed counts                             (D1)
  ├─ dirty_files()   → now meaningful for an orphan checkout             (D2)
  ├─ unpushed()      → now meaningful for an orphan checkout             (D2)
  └─ rmtree / git worktree remove
```

### Orphan taxonomy (the contract this feature establishes)

| Orphan shape | How it is detected | dirty / unpushed gates | nested gate |
|---|---|---|---|
| Plain container (no `.git`, no nested registrations) — e.g. an emptied pool dir | no `.git`, `nested_registered == []` | n/a, nothing to lose | n/a → removable as today |
| Pool dir holding registered children | `nested_registered != []` | evaluated **per child**, reported | REFUSE unless `--force` |
| Deregistered checkout | `.git` present | evaluated **on itself** | n/a |
| Symlink | `child.is_symlink()` | n/a | skipped in `discover()` with a warning |

### Why a new gate rather than refusing in `discover()`

Dropping nested-holding pool dirs from the orphan list would make them
invisible to `list` and silently unremovable, which trades a data-loss bug for
a confusing one. Enrolling them and refusing in `_remove_one()` keeps them
listed, explains the refusal, names the children, and leaves `--force` as a
deliberate informed override — the same shape as every other gate in this file.

### Data Models

```python
# packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py
@dataclass
class Worktree:
    path: Path
    branch: str | None
    registered: bool
    primary: bool = False
    live_processes: list[tuple[int, str]] = field(default_factory=list)
    nested_registered: list[Path] = field(default_factory=list)  # NEW
```

`nested_registered` holds absolute, resolved paths of registered worktrees that
live **below** `path`, sorted, excluding `path` itself. It is empty for every
registered worktree and for every orphan that holds none, so no existing
behaviour keys off it.

### New Public Interfaces

No new public functions. `Worktree` gains one field with a default, so every
existing construction site stays valid.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: discover detection | yes | field name/type, `is_relative_to` test, symlink skip + warning text | — |
| M2: nested + orphan-checkout gates | yes | gate order, refusal wording, exit code 1, `--force` override | — |
| M3: list / dry-run disclosure | yes | STATE token and header line format fixed below | — |
| M4: tests | yes | existing `_git_repo` harness, one test per defect | — |
| M5: doc sync | yes | 3 hand-edited sources + `check_asset_sync.py --write` to regenerate the shipped tree | — |

M1 → M2 → M3 all edit the **same file** and must land in that order; they are
not parallelisable. M4 depends on M1-M3. M5 is independent of the code.

### Module 1: `discover()` — see below the top level, skip symlinks
- **Path**: `packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py`
- **Responsibility**: Populate `Worktree.nested_registered`; never enrol a
  symlink as an orphan.
- **Depends on**: nothing (first change)
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py  (modifies L191-232)
  @dataclass
  class Worktree:  # modifies L77-145
      nested_registered: list[Path] = field(default_factory=list)
      """Registered worktree paths that live below ``path`` (orphans only)."""

  def discover() -> list[Worktree]:
      """Enumerate registered worktrees plus orphan directories.

      An entry that is a symlink is skipped with a warning on stderr: rmtree
      refuses a symlink, and enrolling one aborts a --stale sweep part-way.
      An orphan carries every registered worktree path found below it in
      ``nested_registered`` so the gates in ``_remove_one`` can refuse.
      """
  ```

### Module 2: `_remove_one()` + gates — refuse what would lose work
- **Path**: `packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py`
- **Responsibility**: Add the nested-registration gate; make the dirty and
  unpushed gates meaningful for an orphan that is itself a checkout.
- **Depends on**: Module 1
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py
  def dirty_files(self) -> list[str]:  # modifies L97-102
      """Return porcelain status lines, empty when clean.

      Short-circuits only when the path is absent or is not a checkout at
      all (no ``.git``); a deregistered orphan checkout IS gated.
      """

  def unpushed(self) -> list[str]:  # modifies L104-121
      """Return commits on this branch that origin does not have.

      Same checkout test as ``dirty_files``; the ``origin/dev..HEAD``
      fallback for a branch without an upstream is unchanged.
      """

  def _remove_one(wt: Worktree, args: argparse.Namespace) -> int:  # modifies L292-364
      """Apply the safety gates and remove one worktree.

      New gate, after the live-process gate and before the dirty gate: an
      orphan whose ``nested_registered`` is non-empty is REFUSED unless
      ``--force``, printing each nested worktree with its own dirty and
      unpushed counts. Returns 1 on refusal.
      """
  ```

### Module 3: Disclosure in `list` and `--dry-run`
- **Path**: `packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py`
- **Responsibility**: Stop describing a nested-holding directory as having no
  git record.
- **Depends on**: Module 1
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py
  def cmd_list(args: argparse.Namespace) -> int:  # modifies L235-266
      """Print every worktree with its safety-relevant state.

      An orphan with nested registrations reports ``holds N registered`` in
      the STATE column instead of a bare orphan marker.
      """
  # _remove_one header (L295): when nested_registered is non-empty, print
  #   "(orphan directory, holds N registered worktree(s))"
  # instead of "(orphan directory, no git record)".
  # The --dry-run line (L335-337) names them too.
  ```

### Module 4: Tests
- **Path**: `packages/ai-parrot/tests/sdd/test_scripts_ledger_worktree.py`
- **Responsibility**: One regression test per defect, plus the
  still-removable plain-container case.
- **Depends on**: Modules 1-3
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/tests/sdd/test_scripts_ledger_worktree.py  (appends)
  def test_stale_refuses_orphan_holding_registered_worktree(tmp_path, monkeypatch) -> None:
      """D1: a pool dir holding a registered child survives --stale."""
  def test_stale_force_still_reports_nested_registrations(tmp_path, monkeypatch, capsys) -> None:
      """D1: --force names each nested worktree before removing."""
  def test_stale_refuses_dirty_orphan_checkout(tmp_path, monkeypatch) -> None:
      """D2: a deregistered checkout with uncommitted work is gated."""
  def test_stale_skips_symlinked_orphan(tmp_path, monkeypatch) -> None:
      """D3: a symlink is skipped and the sweep completes."""
  def test_stale_still_removes_plain_container(tmp_path, monkeypatch) -> None:
      """Non-regression: an empty pool dir is still swept."""
  ```

### Module 5: Documentation sync
- **Edited by hand** (the three repo-root sources, registered in
  `scripts/sdd/check_asset_sync.py` `ASSET_SOURCES` at L34/L40/L43):
  - `.claude/commands/remove-worktree.md` (all hosts)
  - `.agents/skills/remove-worktree/SKILL.md` (codex, google)
  - `.agent/workflows/remove-worktree.md` (google)
- **Generated, never hand-edited** — produced by
  `python scripts/sdd/check_asset_sync.py --write`:
  - `packages/ai-parrot/src/parrot/sdd/_assets/claude/commands/remove-worktree.md`
  - `packages/ai-parrot/src/parrot/sdd/_assets/agents/skills/remove-worktree/SKILL.md`
  - `packages/ai-parrot/src/parrot/sdd/_assets/agent/workflows/remove-worktree.md`
  - `packages/ai-parrot/src/parrot/sdd/_assets/manifest.json`
- **Responsibility**: Document the orphan taxonomy from §2 and the new
  refusal in the three sources, then regenerate the shipped copies. The
  `_assets/` tree is what `parrot sdd install` ships, so skipping the
  regeneration leaves an installed repo promising the old gate semantics.
- **Depends on**: Module 2 (wording follows the implemented refusal)
- **Verified**: `check_asset_sync.py --check` exits 0 on the base commit, so
  any `_assets/` drift this feature introduces is its own.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_stale_refuses_orphan_holding_registered_worktree` | M1+M2 | Pool dir with a registered child: `--stale` exits non-zero, dir and child both survive |
| `test_stale_force_still_reports_nested_registrations` | M2+M3 | `--force` prints each nested path before removing |
| `test_stale_refuses_dirty_orphan_checkout` | M2 | Deregistered checkout with an uncommitted file: `--stale` refuses, `--force` removes |
| `test_stale_skips_symlinked_orphan` | M1 | Symlink under `.claude/worktrees/` is skipped, no `OSError`, later targets still swept |
| `test_stale_still_removes_plain_container` | M1+M2 | Empty pool dir is still removed by `--stale` without `--force` |
| `test_remove_worktree_refuses_dirty` | — | Existing test at L173 must keep passing (registered-worktree gate untouched) |

Harness is the existing one in this file: `_git_repo()` (L134) builds a repo on
branch `feature-x`, then `monkeypatch.chdir(primary)`,
`remove_worktree._ROOT = None`, and `remove_worktree.main([...])` is asserted on
exit code plus filesystem state.

### Integration Tests

None. This script shells out to `git` and is covered end-to-end by the unit
tests above, which use real `git worktree add`.

### Validation Contract

tests:
- packages/ai-parrot/tests/sdd/test_scripts_ledger_worktree.py
markers: none

### Test Data / Fixtures

```python
# Reuses the existing module-level helper, no new fixtures:
def _git_repo(path: Path) -> Path:  # test_scripts_ledger_worktree.py:134
    """git init -q -b feature-x + one empty commit; returns path."""
```

A nested-registration fixture is built inline per test:

```python
primary = _git_repo(tmp_path / "repo")
pool = primary / ".claude" / "worktrees" / "feat-FEAT-999-x--pool"
pool.mkdir(parents=True)
child = pool / "TASK-1-a1"
subprocess.run(["git", "worktree", "add", "-q", str(child), "-b", "t1"], cwd=primary, check=True)
```

---

## 5. Acceptance Criteria

- [ ] AC1 — `--stale` refuses a directory holding a registered worktree,
  exits non-zero, and leaves both the directory and the registered child on
  disk (D1, `issue:751782605094`).
- [ ] AC2 — The refusal names every nested registered worktree and reports
  each one's own dirty and unpushed counts.
- [ ] AC3 — `--stale --force` on such a directory still prints the nested
  registrations before removing, so the override is informed.
- [ ] AC4 — `--stale` refuses an orphan directory that is itself a checkout
  with uncommitted changes or unpushed commits, and `--force` is required to
  discard them (D2, `issue:65a431065cae`).
- [ ] AC5 — A symlink under `.claude/worktrees/` is skipped with a warning on
  stderr; no `OSError` escapes, and orphans enumerated after it are still
  processed (D3, `issue:65a431065cae`).
- [ ] AC6 — `list` and `--dry-run` report `holds N registered` for such a
  directory and never call it `(orphan directory, no git record)` (G4).
- [ ] AC7 — An orphan that is a plain container (no `.git`, no nested
  registrations) is still removed by `--stale` without `--force` — the sweep
  stays useful for its actual purpose.
- [ ] AC8 — Gate behaviour for registered worktrees is byte-for-byte
  unchanged; `test_remove_worktree_refuses_dirty` and
  `test_remove_worktree_list_and_dry_run` pass untouched.
- [ ] AC9 — The three repo-root `/remove-worktree` docs describe the orphan
  taxonomy and the new refusal, the shipped `_assets/` copies are regenerated
  with `python scripts/sdd/check_asset_sync.py --write`, and
  `python scripts/sdd/check_asset_sync.py --check` exits 0 (G5). The
  `_assets/` copies are never hand-edited.
- [ ] AC10 — `pytest packages/ai-parrot/tests/sdd/test_scripts_ledger_worktree.py`
  passes, and `ruff check` is clean on every changed file.

---

## 6. Codebase Contract

### Verified Imports

```python
from parrot.sdd.scripts import remove_worktree  # verified: packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py
from parrot.sdd.cli import VERBS, mounted_modules  # verified: tests/sdd/test_scripts_ledger_worktree.py:197-200
```

Module-level imports already present at L38-47 — `argparse`, `Collection`,
`os`, `subprocess`, `sys`, `dataclass`/`field`, `Path`, `Sequence`. `shutil` is
imported **locally** inside the `else` branch of `_remove_one` (L349); keep it
there or hoist it, but do not assume a module-level `shutil`.

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py
PROTECTED_BRANCHES = {"main", "dev", "staging", "master"}        # line 50

@dataclass
class Worktree:                                                   # L77-145
    path: Path                                                    # line 87
    branch: str | None                                            # line 88
    registered: bool                                              # line 89
    primary: bool = False                                         # line 90
    live_processes: list[tuple[int, str]] = field(default_factory=list)  # line 91
    @property
    def name(self) -> str: ...                                    # L94-95
    def dirty_files(self) -> list[str]: ...                       # L97-102
    def unpushed(self) -> list[str]: ...                          # L104-121
    def pr_state(self) -> str | None: ...                         # L123-145

def repo_root() -> Path: ...                                      # L53-60
def _root() -> Path: ...                                          # L63-68
def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess: ...  # L71-73
def live_processes_in(path: Path, exclude_pids: Collection[int] = ()) -> list[tuple[int, str]]: ...  # L164-188
def discover() -> list[Worktree]: ...                             # L191-232
def cmd_list(args: argparse.Namespace) -> int: ...                # L235-266
def _match(worktrees: list[Worktree], target: str) -> list[Worktree]: ...  # L269-289
def _remove_one(wt: Worktree, args: argparse.Namespace) -> int: ...  # L292-364
def cmd_remove(args: argparse.Namespace) -> int: ...              # L367-404
def main(argv: Sequence[str] | None = None) -> int: ...           # L407-434
```

Exact current orphan-enrolment loop, L219-225 — the site Module 1 changes:

```python
registered_paths = {w.path.resolve() for w in worktrees}
worktree_dir = _root() / ".claude" / "worktrees"
if worktree_dir.is_dir():
    for child in sorted(worktree_dir.iterdir()):
        if not child.is_dir():
            continue
        if child.resolve() in registered_paths:
            continue
        worktrees.append(Worktree(path=child, branch=None, registered=False))
```

Exact current `--stale` target selection, `cmd_remove` L370-375:

```python
if args.stale:
    targets = [w for w in worktrees if not w.registered]
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `Worktree.nested_registered` | `discover()` orphan enrolment | constructor kwarg | `remove_worktree.py:225` |
| nested gate | `_remove_one()` gate chain | new branch after live-process gate (L305-314) | `remove_worktree.py:316` |
| nested gate | `--force` | `args.force`, same flag the dirty/unpushed gates read | `remove_worktree.py:317, 326` |
| disclosure | `_remove_one` header | `print(f"  branch: {...}")` | `remove_worktree.py:295` |
| disclosure | `cmd_list` STATE column | existing per-worktree print loop | `remove_worktree.py:241-266` |
| tests | `remove_worktree.main` | `main(["remove", "--stale"])` | `test_scripts_ledger_worktree.py:158-186` |
| tests | root resolution | `remove_worktree._ROOT = None` before each call | `test_scripts_ledger_worktree.py:156` |

### Does NOT Exist (Anti-Hallucination)

- ~~`Worktree.nested_registered`~~ — this feature **adds** it; it is not there today.
- ~~`Worktree.dirty_unknown` / `unpushed_unknown`~~ — those flags belong to
  `worktree_status.py` (the `/sdd-status` panel), **not** to this script. Do not
  import or imitate them here.
- ~~`remove_worktree.WORKTREE_DIR`~~ — no such constant; the path is built
  inline as `_root() / ".claude" / "worktrees"` at L220.
- ~~a module-level `import shutil`~~ — it is a function-local import at L349.
- ~~`args.recursive` / `args.keep_nested`~~ — no such flags; this feature adds
  none. `--force` is the only override.
- ~~`parrot sdd worktree remove --stale --dry-run` printing nested children~~ —
  it does not today (the dry-run branch at L335-337 runs after the gates and
  prints one generic line); AC6 makes it.

### Edit Sites (Blueprint Anchors)

Verified against base commit `da42a5fe34` (dev, 2026-11-06).

| File | Anchor | Module |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py` | `live_processes: list[tuple[int, str]] = field(default_factory=list)` | M1 |
| `packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py` | `for child in sorted(worktree_dir.iterdir()):` | M1 |
| `packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py` | `if not self.registered or not self.path.exists():` | M2 (2 occurrences — `dirty_files` L99 and `unpushed` L112) |
| `packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py` | `if dirty and not args.force:` | M2 (the gate; **not** `dirty = wt.dirty_files()`, which is ambiguous — see note) |
| `packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py` | `print(f"  branch: {wt.branch or '(orphan directory, no git record)'}")` | M3 |
| `packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py` | `flags.append("ORPHAN-DIR")` | M3 (the `cmd_list` STATE column, L245) |
| `packages/ai-parrot/tests/sdd/test_scripts_ledger_worktree.py` | `def test_remove_worktree_shim_aliases() -> None:` | M4 (insert the new tests above it) |
| `.claude/commands/remove-worktree.md`, `.agents/skills/remove-worktree/SKILL.md`, `.agent/workflows/remove-worktree.md` | the orphan/gate description (sources only — `_assets/` is regenerated, never edited) | M5 |

> **Ambiguous anchor warning.** `dirty = wt.dirty_files()` occurs **twice** —
> L249 inside `cmd_list`'s flag loop (8-space indent) and L316 inside
> `_remove_one`'s gate (4-space indent). `unpushed = wt.unpushed()` is
> likewise doubled (L252 / L326). Anchor on the following `if ... and not
> args.force:` line for the gate sites and on `flags.append("ORPHAN-DIR")`
> for the listing site; never on the bare assignment.

---

## 7. Ledger Provenance

This spec drains one `/sdd-fix` group.

| Issue | Severity | Kind | Defect | Closed by |
|---|---|---|---|---|
| `issue:751782605094` | major | bug | D1 | the task implementing M1+M2 |
| `issue:65a431065cae` | minor | tech_debt | D2 + D3 | the task implementing M1+M2 |

Group `fixgroup:9ece73bf1b55`, lane `sdd` (`max_severity is major`), claimed by
`agent:sdd-fix:118971f4`. Both issues name
`packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py` as their only
file, which is the diff key `/sdd-done` checks before closing them.

Every task filed for this spec MUST carry the matching
`**Discovered-from**: `issue:<id>`` trailer — that link is how `/sdd-done`
finds the issues to close.

Prior art: `mem-75ce04f1d364` (wiki lesson, D1 mechanism and the
remove-children-first workaround).
