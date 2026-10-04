---
type: feature
base_branch: dev
projects: [sdd-tooling]
tags: [sdd, worktree, observability, cli, tech-debt]
---

# Feature Specification: worktree_status Tech-Debt Drain (FEAT-582 follow-up)

**Feature ID**: FEAT-619
**Date**: 2026-10-01
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.0.7

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-582 shipped `scripts/sdd/worktree_status.py`, the library behind the
`/sdd-status` and `/sdd-next` worktree panels. Its adversarial code review
(2026-09-19, TASK-3549) raised six findings that were verified but
deliberately **not** fixed in-feature, because none of them failed FEAT-582's
own acceptance criteria. They were filed in the work ledger as
`fixgroup:13323ccb5fcc` and are the entire scope of this feature:

| Ledger issue | Sev | Defect |
|---|---|---|
| `issue:07b75dc7dfae` | major | Non-SDD worktrees never appear in `--json`, although the spec resolved to show them and both command twins document a worked example row |
| `issue:6b0b91e1f5b2` | minor | `_check_health` ignores git's returncode, so "could not check" is reported as "clean" |
| `issue:8aef2c10c7fd` | minor | `_read_worktree_index`'s except clause misses realistic `OSError`/`UnicodeDecodeError` subtypes |
| `issue:f3dabdbe09a8` | minor | `discover_worktree_reports` output order is nondeterministic (set iteration) |
| `issue:0974a2a92df3` | low | Misleading "verified:" anchor comment on the `WORKTREE_ROOT` import |
| `issue:4456385c283c` | low | CLI table prints `feature_id` twice (Name column + Feature column) |

The major finding is a **documentation/implementation divergence**, which is
worse than a plain gap. `sdd/specs/sdd-status-worktrees.spec.md` §8 resolved
*"Should non-SDD worktrees (chore-*, fix-*) be shown?"* as **"Yes, in the
Worktrees panel only (no task board entry since they have no per-spec
index)."** Both `.claude/commands/sdd-status.md` §5 and
`.agents/skills/sdd-status/SKILL.md` step 6 then documented that behaviour,
including a literal worked example:

```
  chore-ruff-config  (non-SDD)
    Branch: chore-ruff-config
    Health: clean
```

But `discover_worktree_reports()` `continue`s past every branch
`_parse_branch()` cannot parse, so `--json` can never emit such an entry. An
agent following `/sdd-status` literally must either hallucinate the row or
silently drop documented behaviour.

The gap is not hypothetical: this checkout currently has ~14 worktrees whose
branches do not parse as SDD branches (`chore-ruff-config`,
`fix-codeql-pipeline`, `sdd-close-feat-537-human-gate`,
`hotfix-openai-max-completion-tokens`, `fix/98205ecd666b-...`, and the
`feat-FEAT-566-sdd-work-ledger` directory whose branch is actually
`fix-FEAT-566-async-io-fsync-followup`). Every one is invisible to
`/sdd-status` today — precisely the stale worktrees an operator most needs to
see.

The `_check_health` finding compounds it: `ready_for_done` exists to stop
`/sdd-status` suggesting an unsafe `/sdd-done`, so treating "git failed" as
"confirmed clean" is a correctness risk, not a cosmetic one.

### Goals

1. Emit a `WorktreeReport` for non-SDD worktrees under `WORKTREE_ROOT`, so the
   documented panel row has a real data source (`issue:07b75dc7dfae`).
2. Make health checks fail closed: an unreadable git state is reported as
   *unknown*, never as *clean*, and never satisfies `ready_for_done`
   (`issue:6b0b91e1f5b2`).
3. Make one malformed worktree index incapable of crashing the whole scan,
   for the full realistic exception set (`issue:8aef2c10c7fd`).
4. Make `--json` and table output byte-stable across runs for unchanged
   underlying state (`issue:f3dabdbe09a8`).
5. Clear the two nitpicks (`issue:0974a2a92df3`, `issue:4456385c283c`).
6. Keep the documented `/sdd-status` behaviour and the implementation in sync,
   in **both** command twins plus the skill.

### Non-Goals (explicitly out of scope)

- No task-board entry for non-SDD worktrees. FEAT-582 §8 scoped them to the
  Worktrees panel only; they have no per-spec index, so `--reconcile` output
  must be byte-identical to today's.
- No new CLI flags, no change to the `--reconcile` data model
  (`ReconciledTask` / `ReconciledFeature` are untouched).
- No change to `_live_process_count`, `_parse_porcelain`, or
  `reconcile_feature`'s merge semantics.
- Not a rewrite: `scripts/sdd/worktree_status.py` stays a single read-only
  module with the same public entry points.
- No `/remove-worktree` integration, no automatic cleanup of the stale
  worktrees this change makes visible.

---

## 2. Architectural Design

### Overview

Three of the six fixes are local edits inside existing functions. The major
one needs a small, additive model change plus a restructured discovery loop.

The key design decision is **how a non-SDD worktree is represented**. The
ledger issue offered two options: make `feature_slug`/`feature_id` fully
optional, or add a separate lightweight entry type. Both break or fork every
consumer (`main()`'s table, `reconcile_reports`' lookup maps, the two command
twins' JSON readers).

This spec takes a third, strictly additive route: **keep `WorktreeReport` as
the single entry type, widen `flow_type` with a third literal `"non-sdd"`,
and carry the branch name in `feature_slug`.** `feature_id` is `None`,
`tasks` is empty, `index_found` is `False`, `ready_for_done` is `False`.
`flow_type` becomes the discriminator every consumer keys on. No field
becomes optional, no existing field changes meaning for SDD worktrees, and
the table's "Name" column already prints what the documented example shows.

Two containment guards are mandatory, and both are easy to miss:

1. **Only paths under `WORKTREE_ROOT` may produce a non-SDD entry.** The
   primary checkout is itself a row in `git worktree list --porcelain`, on
   branch `dev`, which does not parse as an SDD branch. Without this guard the
   main repo appears in its own Worktrees panel.
2. **sdd-coder pool sub-worktrees must still be skipped.** They live *under*
   `WORKTREE_ROOT` and their branches do not parse either, so guard 1 does not
   cover them. This checkout has 12 of them right now; emitting them would
   bury the real rows. `_parse_branch()` returns `None` for both pool branches
   and non-SDD branches, so the discovery loop must test
   `_POOL_SUB_WORKTREE_RE` explicitly rather than inferring from `None`.

### Component Diagram

```
discover_worktree_reports(repo_root)
  ├── _git("worktree","list","--porcelain") ──► _parse_porcelain()
  ├── scan WORKTREE_ROOT for orphan dirs
  ├── sorted(all_worktree_paths)                      ← M1: determinism
  └── for each path:
        ├── resolve branch
        ├── _POOL_SUB_WORKTREE_RE? ────────────────► skip          ← M1 (guard 2)
        ├── _parse_branch() is None?
        │     ├── under WORKTREE_ROOT? ──► non-SDD WorktreeReport  ← M1 (guard 1)
        │     └── else ─────────────────► skip
        └── SDD branch ──► _read_worktree_index()     ← M2 (broadened except)
                           _check_health()            ← M2 (returncode → unknown)
                           ready_for_done &= not unknown
      └── return sorted(reports, key=(branch, worktree_path))   ← M1: determinism

reconcile_reports(repo_root, reports)
  └── filters flow_type == "non-sdd" out of both lookup maps      ← M1
      (--reconcile output byte-identical to today)
```

### Data Models

**`WorktreeHealth`** — two additive fields, both defaulting to the current
behaviour:

```python
class WorktreeHealth(BaseModel):
    dirty_count: int = 0
    unpushed_count: int = 0
    live_process_count: int = 0
    #: git status failed — dirty_count is not trustworthy (FEAT-619)
    dirty_unknown: bool = False
    #: git log failed (e.g. origin/<base> missing) — unpushed_count is not trustworthy
    unpushed_unknown: bool = False
```

Two flags rather than one, because they map to the two distinct git calls and
an operator needs to know *which* signal is unreadable. The common real cause
is a missing `origin/<base_branch>` ref (a worktree cut from `staging` during
a release freeze, or simply an unfetched remote), which fails only the `log`
call.

**`WorktreeReport`** — one widened literal:

```python
flow_type: Literal["feature", "hotfix", "non-sdd"]
```

Field semantics for a `"non-sdd"` report:

| Field | Value |
|---|---|
| `feature_slug` | the branch name (`"chore-ruff-config"`) |
| `feature_id` | `None` |
| `flow_type` | `"non-sdd"` |
| `worktree_path` / `branch` | as discovered |
| `base_branch` | `"dev"` (not read from any index) |
| `health` | fully populated — this is the point of the row |
| `tasks` | `[]` |
| `index_found` | `False` |
| `ready_for_done` | `False` (always) |

### Integration Points

- `.claude/commands/sdd-status.md` §5 + its twin `.agent/workflows/sdd-status.md`
  — the worked example becomes reachable; the health-flag list gains `unknown`.
- `.agents/skills/sdd-status/SKILL.md` step 6 — same, one line.
- `.claude/commands/sdd-next.md` / `.agents/skills/sdd-next/SKILL.md` consume
  `--json` for `ready_for_done`. They must learn to ignore `"non-sdd"` rows
  (they have no tasks to suggest).

---

## 3. Module Breakdown

### Module 1: Non-SDD discovery + deterministic order (`scripts/sdd/worktree_status.py`)

Closes `issue:07b75dc7dfae` and `issue:f3dabdbe09a8`.

1. Widen `WorktreeReport.flow_type` to `Literal["feature", "hotfix", "non-sdd"]`.
2. In `discover_worktree_reports`, iterate `sorted(all_worktree_paths)` instead
   of the raw set.
3. Resolve `worktree_root = (repo_root / WORKTREE_ROOT).resolve()` once, and
   add a containment helper (`path == worktree_root or worktree_root in
   path.parents`).
4. Restructure the per-path body: after the branch is resolved, skip when
   `_POOL_SUB_WORKTREE_RE.search(branch)`; then on `_parse_branch(branch) is
   None`, emit a non-SDD report **only** when the path is contained in
   `worktree_root`, else `continue`.
5. Non-SDD reports still get `_check_health(wt_path, "dev")` — health is the
   whole value of the row.
6. `return sorted(reports, key=lambda r: (r.branch, r.worktree_path))`.
7. In `reconcile_reports`, exclude `flow_type == "non-sdd"` from `by_feature_id`
   and `by_slug`, and from the worktree-only append loop.

Note: the detached-HEAD path already `continue`s when `rev-parse` fails. When
`rev-parse` *succeeds* on a detached HEAD it returns the literal `"HEAD"`,
which now yields a non-SDD row named `HEAD` for a worktree under
`WORKTREE_ROOT`. That is intended — a detached pool-less worktree is exactly
the kind of orphan the panel should surface.

### Module 2: Fail-closed health + broadened index read (`scripts/sdd/worktree_status.py`)

Closes `issue:6b0b91e1f5b2` and `issue:8aef2c10c7fd`.

1. `_check_health`: check `.returncode` on both `_git` results. On non-zero,
   leave the count at `0` and set the matching `*_unknown` flag.
2. `discover_worktree_reports`: extend the `ready_for_done` conjunction with
   `and not health.dirty_unknown and not health.unpushed_unknown`.
3. `_read_worktree_index`: broaden
   `except (FileNotFoundError, json.JSONDecodeError, KeyError)` to
   `except (OSError, json.JSONDecodeError, UnicodeDecodeError, KeyError)`.
   `FileNotFoundError`, `PermissionError` and `IsADirectoryError` are all
   `OSError` subclasses; `UnicodeDecodeError` is a `ValueError` subclass and
   must be named separately.

### Module 3: CLI table + anchor comment (`scripts/sdd/worktree_status.py`)

Closes `issue:4456385c283c` and `issue:0974a2a92df3`.

1. `main()`'s plain table: the Name column prints `r.feature_slug` alone;
   append `" (non-SDD)"` when `flow_type == "non-sdd"`. The dedicated Feature
   column keeps printing `r.feature_id or '-'`, so the id appears exactly once.
2. Health column: render `unknown` (or `dirty:unknown` / `unpushed:unknown`)
   when the corresponding flag is set, so the table never shows a bare `clean`
   for an unreadable worktree.
3. Fix the import comment to point at the real definition:
   `# verified: packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py:322`
   (`scripts/sdd/sdd_meta.py` is a re-export shim; its line 15 is an import
   list entry, not the definition).

### Module 4: Documentation twins

1. `.claude/commands/sdd-status.md` §5 and its twin `.agent/workflows/sdd-status.md`:
   add the `unknown` health flag to the flag list; state that non-SDD rows come
   from `flow_type: "non-sdd"` entries in `WT_REPORTS`. The existing worked
   example stays as-is — it becomes correct rather than aspirational.
2. `.agents/skills/sdd-status/SKILL.md` step 6: same one-line addition.
3. `.claude/commands/sdd-next.md` + `.agents/skills/sdd-next/SKILL.md`: note
   that `"non-sdd"` entries carry no tasks and are not suggestion candidates.

Both `.claude/` and `.agent*/` copies must be edited — they are twins, and
`.gitignore` may require `git add -f`.

### Module 5: Tests (`tests/sdd_scripts/test_worktree_status.py`)

Extend the existing suite; do not restructure it. The module already has
`TestParseBranch`, `TestParsePorcelain`, `TestReadWorktreeIndex`, `TestHealth`,
`TestReadyForDone`, `TestDiscover`, `TestCli`, `TestReconcileFeature`,
`TestReconcileReports`, `TestReconcileCli` and the
`_discover_with_fake_worktree` helper. New cases attach to those classes.

---

## 4. Test Specification

### Unit Tests

**Non-SDD discovery (`issue:07b75dc7dfae`)**
- A worktree under `WORKTREE_ROOT` on branch `chore-ruff-config` yields one
  report with `flow_type == "non-sdd"`, `feature_slug == "chore-ruff-config"`,
  `feature_id is None`, `tasks == []`, `index_found is False`,
  `ready_for_done is False`.
- Its `health` is populated from the mocked git calls (not left at defaults).
- The **primary checkout** (repo_root, branch `dev`, outside `WORKTREE_ROOT`)
  produces **no** report.
- A pool sub-worktree branch
  (`feat-FEAT-616-...--TASK-3891-a1-4c8992efd3f44e8a81cc4f0c713c8677`) under
  `WORKTREE_ROOT` produces **no** report.
- A real SDD worktree in the same scan still produces its normal
  `flow_type == "feature"` report with tasks (no regression).

**Determinism (`issue:f3dabdbe09a8`)**
- `discover_worktree_reports` over a fixture with ≥3 worktrees returns the same
  `[r.branch for r in reports]` across repeated calls, and that list equals its
  own `sorted()`.

**Fail-closed health (`issue:6b0b91e1f5b2`)**
- `_git("status", ...)` returning `returncode=1` → `dirty_unknown is True`,
  `dirty_count == 0`.
- `_git("log", ...)` returning `returncode=128` (missing `origin/<base>`) →
  `unpushed_unknown is True`, `unpushed_count == 0`.
- Both succeeding → both flags `False` (guards the default path).
- A worktree whose tasks are all `done` but whose health is unknown has
  `ready_for_done is False` — the regression this issue is really about.
- The existing `test_git_missing_worktree_directory_does_not_raise` keeps its
  current assertions and gains `dirty_unknown is True` /
  `unpushed_unknown is True`.

**Index read robustness (`issue:8aef2c10c7fd`)**
- `PermissionError`, `IsADirectoryError` and `UnicodeDecodeError` raised from
  the `open`/`json.load` boundary each return `([], "dev")` without
  propagating. Parametrize over the three.

**CLI (`issue:4456385c283c`)**
- `main()` plain-table output for a report with `feature_id="FEAT-550"`
  contains `"FEAT-550"` exactly once per row.
- A non-SDD report's row contains `"(non-SDD)"` and no task counts.
- A report with `dirty_unknown=True` renders `unknown` in the health column,
  not `clean`.

**`--reconcile` non-regression**
- `reconcile_reports` given a mixed list (SDD + non-SDD reports) returns
  exactly what it returns for the SDD-only list — non-SDD entries never reach
  the task board.

### Test Data / Fixtures

Reuse `_discover_with_fake_worktree`'s mocking shape (`patch` on
`scripts.sdd.worktree_status._git`, `WORKTREE_ROOT`, `_live_process_count`).
It currently builds exactly one worktree and filters to `FEAT-550`; a
multi-worktree variant (or a `branches=` parameter) is needed for the
determinism and primary-checkout cases. Extend it rather than duplicating it.

---

## 5. Acceptance Criteria

- **AC1** — A worktree under `WORKTREE_ROOT` whose branch does not parse as an
  SDD branch appears in `discover_worktree_reports` output with
  `flow_type: "non-sdd"`, and therefore in `--json`.
- **AC2** — The primary checkout never appears in its own report list.
- **AC3** — sdd-coder pool sub-worktrees never appear in the report list.
- **AC4** — `--json` and plain-table row order are identical across repeated
  runs against unchanged state, and sorted by `(branch, worktree_path)`.
- **AC5** — A failed `git status` or `git log` sets the matching `*_unknown`
  flag and never reports `clean`; `ready_for_done` is `False` whenever either
  flag is set.
- **AC6** — `_read_worktree_index` returns `([], "dev")` for `PermissionError`,
  `IsADirectoryError` and `UnicodeDecodeError` without propagating.
- **AC7** — Each plain-table row prints `feature_id` exactly once.
- **AC8** — The `WORKTREE_ROOT` import comment names the defining file and line.
- **AC9** — `--reconcile` output is unchanged by this feature for any input
  containing no non-SDD worktrees, and ignores non-SDD entries when present.
- **AC10** — `.claude/commands/sdd-status.md`, `.agent/workflows/sdd-status.md`
  and `.agents/skills/sdd-status/SKILL.md` describe the `unknown` health state
  and the `"non-sdd"` discriminator; the `/sdd-next` twins note that non-SDD
  rows are not suggestion candidates.
- **AC11** — The full existing `tests/sdd_scripts/test_worktree_status.py`
  suite passes unmodified except for additive assertions.

---

## 6. Codebase Contract

### Verified Imports

```python
from scripts.sdd.worktree_status import (     # verified: tests/sdd_scripts/test_worktree_status.py:13-27
    WorktreeHealth, WorktreeReport, WorktreeTaskStatus,
    _check_health, _git, _load_dev_indexes, _parse_branch, _parse_porcelain,
    _read_worktree_index, discover_worktree_reports, main,
    reconcile_feature, reconcile_reports,
)
from scripts.sdd.sdd_meta import WORKTREE_ROOT   # re-export shim; defined at
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py:322 → ".claude/worktrees"
```

### Existing Signatures

```python
# scripts/sdd/worktree_status.py
_FEAT_BRANCH_RE   = re.compile(r"^feat-(?:FEAT-)?(\d+)-(.+)$")          # line 26
_HOTFIX_BRANCH_RE = re.compile(r"^hotfix-([A-Z]+-\d+)-(.+)$")           # line 27
_POOL_SUB_WORKTREE_RE = re.compile(r"--TASK-\d+-a\d+-[0-9a-f]+$")       # line 32

def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]     # line 75
def _parse_branch(branch: str) -> tuple[str, str | None, Literal["feature","hotfix"]] | None   # line 99
def _read_worktree_index(wt_path: Path, slug: str) -> tuple[list[WorktreeTaskStatus], str]     # line 125
def _live_process_count(path: Path) -> int                              # line 164
def _check_health(wt_path: Path, base_branch: str) -> WorktreeHealth    # line 190
def _parse_porcelain(output: str) -> list[tuple[Path, str | None]]      # line 215
def discover_worktree_reports(repo_root: Path) -> list[WorktreeReport]  # line 248
def reconcile_feature(dev_index: dict | None, report: WorktreeReport | None) -> ReconciledFeature  # line 386
def _load_dev_indexes(repo_root: Path) -> list[dict]                    # line 460
def reconcile_reports(repo_root: Path, reports: list[WorktreeReport]) -> list[ReconciledFeature]  # line 480
def main() -> int                                                       # line 522
```

### Edit Sites (Blueprint Anchors)

| File | Anchor | Change |
|---|---|---|
| `scripts/sdd/worktree_status.py` | line 20 | import comment → real definition anchor |
| `scripts/sdd/worktree_status.py` | lines 47–53 `WorktreeHealth` | + `dirty_unknown`, `unpushed_unknown` |
| `scripts/sdd/worktree_status.py` | line 60 `flow_type` | + `"non-sdd"` literal |
| `scripts/sdd/worktree_status.py` | line 138 `except (...)` | broaden to `OSError`/`UnicodeDecodeError` |
| `scripts/sdd/worktree_status.py` | lines 193–207 `_check_health` | returncode checks → unknown flags |
| `scripts/sdd/worktree_status.py` | lines 266–278 | resolved `worktree_root`, `sorted(...)` iteration |
| `scripts/sdd/worktree_status.py` | lines 295–299 | pool guard + non-SDD emission branch |
| `scripts/sdd/worktree_status.py` | line 313 `ready_for_done` | `and not *_unknown` |
| `scripts/sdd/worktree_status.py` | line 330 `return reports` | `return sorted(...)` |
| `scripts/sdd/worktree_status.py` | lines 497–498 | filter `"non-sdd"` from lookup maps |
| `scripts/sdd/worktree_status.py` | lines 586–613 | Name column, health column |
| `.claude/commands/sdd-status.md` | §5 flag list (~line 177) | `unknown` flag + discriminator |
| `.agent/workflows/sdd-status.md` | §5 flag list (~line 177) | twin of the above |
| `.agents/skills/sdd-status/SKILL.md` | step 6 (~line 53) | one line |
| `.claude/commands/sdd-next.md` | ~line 52 | non-SDD rows are not candidates |
| `.agents/skills/sdd-next/SKILL.md` | ~line 37 | twin of the above |
| `tests/sdd_scripts/test_worktree_status.py` | existing classes | additive cases |

### Does NOT Exist (Anti-Hallucination)

- There is **no** `WorktreeReport.is_sdd`, `.kind`, `.name` or `.display_name`
  field — the discriminator is `flow_type`.
- There is **no** separate `NonSddWorktreeReport` model, and this spec does not
  add one.
- `scripts/sdd/worktree_status.py` has **no** `__all__`, no logger, and no
  `argparse` subcommands — `main()` has exactly two flags, `--json` and
  `--reconcile`.
- There is no `tests/sdd_scripts/conftest.py` fixture for worktrees; the
  fixtures are module-local in `test_worktree_status.py`.
- `WORKTREE_ROOT` is a `str`, not a `Path`.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- The module is **read-only** by contract (module docstring line 3): never add
  a mutating git command. `_git` must keep its "never raises" guarantee.
- Pydantic v2 models, strict type hints, Google-style docstrings, 120 columns,
  `ruff check` clean.
- Additive model changes only: every new field carries a default so existing
  constructions in tests and callers keep working.

### Known Risks / Gotchas

- **Containment check on resolved paths.** `_parse_porcelain` already
  `.resolve()`s every path and the orphan scan resolves too, so
  `worktree_root` must also be resolved before comparing, or a symlinked
  `.claude/worktrees` silently matches nothing and the fix becomes a no-op.
- **`WORKTREE_ROOT` is patched as an absolute path in tests**
  (`patch(..., str(worktree_root))`). `repo_root / WORKTREE_ROOT` with an
  absolute right-hand side discards `repo_root` — correct, but any containment
  helper must handle both the absolute (test) and relative (production) forms.
- **Do not widen `_parse_branch`'s return type.** It stays
  `Literal["feature","hotfix"] | None`; `"non-sdd"` is decided by the caller.
  Changing it would ripple into `TestParseBranch`.
- **`test_git_missing_worktree_directory_does_not_raise` must keep passing.**
  It asserts `dirty_count == 0` / `unpushed_count == 0` for a deleted
  directory; the unknown flags are additive on top, not a replacement.
- Doc twins drift easily — edit `.claude/` **and** `.agent*/` copies in the
  same commit, and check whether `git add -f` is needed.
- This checkout has ~14 non-SDD and ~12 pool worktrees right now, so AC2/AC3
  can be sanity-checked against reality by running the CLI, not only fixtures.

### External Dependencies

None. No new packages; `pydantic` and the stdlib only.

---

## 8. Open Questions

None. Every design decision is fixed by the ledger issues and FEAT-582 §8's
prior resolution; the one genuinely open choice (how to represent a non-SDD
entry) is settled in §2 Overview with its rationale.

---

## 9. Design Research Cross-Check

The six findings come from FEAT-582's own adversarial code review
(TASK-3549 delivery, 2026-09-19) and were triaged then as "verified, not
blocking this feature's ACs". No further research was required; this spec adds
the two containment guards (primary checkout, pool sub-worktrees) that the
original issue text did not identify, found by reading the discovery loop
against this checkout's actual `git worktree list`.

---

## Worktree Strategy

- **Isolation**: one worktree for this feature.
- **Module dependency graph**: M1 and M2 both edit
  `scripts/sdd/worktree_status.py` and must be **sequential** (M1 → M2 → M3).
  M4 (docs) is parallel-safe with all of them. M5 (tests) depends on M1–M3.
- **Shared files**: `scripts/sdd/worktree_status.py` is touched by M1, M2 and
  M3 — the single serialization point of this feature.
- **Exclusive resources**: none.
- **Cross-feature dependencies**: none. FEAT-582 is closed and merged.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-01 | Jesus Lara | Initial draft — drains ledger `fixgroup:13323ccb5fcc` (6 issues) from FEAT-582's code review |
