# TASK-3915: Emit non-SDD worktree reports and make discovery order deterministic

**Feature**: FEAT-619 — worktree_status Tech-Debt Drain (FEAT-582 follow-up)
**Spec**: `sdd/specs/sdd-worktree-status-tech-debt.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec Module 1. Closes two ledger issues from FEAT-582's adversarial
code review:

- `issue:07b75dc7dfae` (**major**) — `discover_worktree_reports()` `continue`s
  past every branch `_parse_branch()` cannot parse, so a non-SDD worktree never
  produces a `WorktreeReport` and `--json` can never emit one. Yet
  `sdd/specs/sdd-status-worktrees.spec.md` §8 resolved *"Should non-SDD
  worktrees be shown?"* as **yes, in the Worktrees panel only**, and both
  `/sdd-status` twins already document a worked example row
  (`chore-ruff-config  (non-SDD)`). An agent following the command literally
  must hallucinate that row or silently drop documented behaviour.
- `issue:f3dabdbe09a8` (minor) — `all_worktree_paths` is a `set`, so `--json`
  array order and table row order vary run to run for identical underlying
  state, which defeats screen-diffing a status tool.

This is the foundation task: it changes the model (`flow_type` literal) that
TASK-3916 and TASK-3917 build on.

---

## Scope

- Widen `WorktreeReport.flow_type` to `Literal["feature", "hotfix", "non-sdd"]`.
- Add a module-level containment helper for "is this path inside WORKTREE_ROOT".
- In `discover_worktree_reports`: iterate paths in sorted order, skip sdd-coder
  pool sub-worktrees explicitly, emit a health-only `WorktreeReport` with
  `flow_type="non-sdd"` for unparseable branches **under WORKTREE_ROOT only**,
  and return the list sorted by `(branch, worktree_path)`.
- In `reconcile_reports`: exclude `flow_type == "non-sdd"` entries from both
  lookup maps and from the worktree-only append loop, so `--reconcile` output
  is unchanged.
- Write tests for all of the above in the existing test module.

**NOT in scope**:
- `_check_health`'s returncode handling and the `*_unknown` flags — TASK-3916.
- `_read_worktree_index`'s except clause — TASK-3916.
- The CLI table's Name/Feature columns and the `WORKTREE_ROOT` import comment
  — TASK-3917.
- Documentation twins — TASK-3918.
- Any change to `_parse_branch`'s signature or return type, to
  `_parse_porcelain`, to `_live_process_count`, or to `reconcile_feature`'s
  merge semantics.
- Any task-board entry for non-SDD worktrees (spec Non-Goals: panel only).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/worktree_status.py` | MODIFY | `flow_type` literal, containment helper, discovery loop, sorted output, reconcile filter |
| `tests/sdd_scripts/test_worktree_status.py` | MODIFY | Non-SDD discovery, guard and determinism tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from scripts.sdd.worktree_status import (     # verified: tests/sdd_scripts/test_worktree_status.py:13-27
    WorktreeHealth,
    WorktreeReport,
    WorktreeTaskStatus,
    _check_health,
    _git,
    _parse_branch,
    _parse_porcelain,
    _read_worktree_index,
    discover_worktree_reports,
    reconcile_reports,
)
from scripts.sdd.sdd_meta import WORKTREE_ROOT  # verified: scripts/sdd/worktree_status.py:20
```

`WORKTREE_ROOT` is a **`str`** (`".claude/worktrees"`), defined at
`packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py:322` and
re-exported by `scripts/sdd/sdd_meta.py`.

### Existing Signatures to Use

```python
# scripts/sdd/worktree_status.py
_POOL_SUB_WORKTREE_RE = re.compile(r"--TASK-\d+-a\d+-[0-9a-f]+$")   # line 32

class WorktreeReport(BaseModel):                                     # line 55
    feature_slug: str                                                # line 58
    feature_id: str | None = None                                    # line 59
    flow_type: Literal["feature", "hotfix"]                          # line 60
    worktree_path: str                                               # line 61
    branch: str                                                      # line 62
    base_branch: str = "dev"                                         # line 63
    health: WorktreeHealth = Field(default_factory=WorktreeHealth)   # line 64
    tasks: list[WorktreeTaskStatus] = Field(default_factory=list)    # line 65
    index_found: bool = True                                         # line 66
    ready_for_done: bool = False                                     # line 67

def _parse_branch(branch: str) -> tuple[str, str | None, Literal["feature", "hotfix"]] | None:  # line 99
def _check_health(wt_path: Path, base_branch: str) -> WorktreeHealth:                            # line 190
def discover_worktree_reports(repo_root: Path) -> list[WorktreeReport]:                          # line 248
def reconcile_reports(repo_root: Path, reports: list[WorktreeReport]) -> list[ReconciledFeature]:  # line 480
```

```python
# tests/sdd_scripts/test_worktree_status.py
def _completed(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess:  # line 78
def _discover_with_fake_worktree(tmp_path, index_data, *, status_out="", log_out=""):  # line 82
# patches: scripts.sdd.worktree_status._git,
#          scripts.sdd.worktree_status.WORKTREE_ROOT (with an ABSOLUTE str),
#          scripts.sdd.worktree_status._live_process_count
```

### Does NOT Exist

- ~~`WorktreeReport.is_sdd`~~ / ~~`.kind`~~ / ~~`.name`~~ / ~~`.display_name`~~ —
  the discriminator is `flow_type`; do not add a new field.
- ~~`NonSddWorktreeReport`~~ — this feature adds no second model.
- ~~`scripts.sdd.worktree_status._is_under_worktree_root`~~ — you create it in
  this task; it does not exist yet.
- ~~`scripts/sdd/worktree_status.py.__all__`~~ — the module has none.
- ~~`tests/sdd_scripts/conftest.py`~~ — does not exist; fixtures are
  module-local in `test_worktree_status.py`.
- ~~`WORKTREE_ROOT` as a `Path`~~ — it is a `str`.

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
    "sym:scripts/sdd/worktree_status.py#WorktreeReport",
    "sym:scripts/sdd/worktree_status.py#discover_worktree_reports",
    "sym:scripts/sdd/worktree_status.py#reconcile_reports",
    "sym:scripts/sdd/worktree_status.py#_parse_branch",
    "sym:scripts/sdd/worktree_status.py#_check_health"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- The module is **read-only by contract** (docstring line 3: *"Read-only: never
  writes files or runs mutating git commands"*). Add no mutating git command.
- Pydantic v2, strict type hints, Google-style docstrings, 120-column lines.
- Additive model change only — `flow_type` gains a literal; no field becomes
  optional and no existing field changes meaning for SDD worktrees.

### Two guards that are easy to miss

1. **The primary checkout is itself a `git worktree list --porcelain` entry**,
   on branch `dev`, which does not parse as an SDD branch. Without the
   WORKTREE_ROOT containment guard the main repo appears in its own Worktrees
   panel.
2. **Pool sub-worktrees live *under* WORKTREE_ROOT**, so guard 1 does not cover
   them. This checkout has 12 right now
   (`.claude/worktrees/feat-FEAT-616-odoo-toolkit-upgrades--pool/TASK-3891-a1-…`).
   `_parse_branch()` returns `None` for pool branches *and* for non-SDD
   branches, so the loop MUST test `_POOL_SUB_WORKTREE_RE` separately — you
   cannot tell the two apart from a `None` return.

### Resolution symmetry gotcha

`_parse_porcelain` already `.resolve()`s every path, and the orphan scan
resolves too. So `worktree_root` must ALSO be resolved before comparing, or a
symlinked `.claude/worktrees` matches nothing and the whole fix is a silent
no-op. Equally: the tests patch `WORKTREE_ROOT` with an **absolute** string, and
`repo_root / "<absolute>"` discards `repo_root` — correct Python, but the
helper must work for both the absolute (test) and relative (production) forms.

---

## Implementation Blueprint

### Steps (in order)

1. Widen the `flow_type` literal — *why*: every later block constructs a report
   with `flow_type="non-sdd"`, which pydantic rejects until the literal admits it.
2. Add `_is_under_worktree_root` next to the other private helpers — *why*: the
   containment test is needed in one place now but is the guard that keeps the
   primary checkout out of its own report, so it deserves a named, testable unit.
3. Resolve `worktree_root` once at the top of `discover_worktree_reports` and
   reuse it for both the orphan scan and the containment test — *why*: resolving
   twice risks the two paths disagreeing after a symlink change mid-scan.
4. Iterate `sorted(all_worktree_paths)` — *why*: set iteration order is the
   root cause of `issue:f3dabdbe09a8`; sorting the input also makes the
   intermediate state deterministic while debugging.
5. Insert the pool guard BEFORE the `_parse_branch` call — *why*: both return
   `None`-ish signals and the pool case must win, or 12 attempt worktrees flood
   the panel.
6. Replace the bare `continue` on `parsed is None` with the containment test +
   non-SDD report construction — *why*: this is the actual fix for
   `issue:07b75dc7dfae`.
7. Sort the returned list by `(branch, worktree_path)` — *why*: step 4 fixes
   input order, but orphan and porcelain paths merge, so the output contract
   must be stated on the way out, where the test can assert it.
8. Filter non-SDD entries out of `reconcile_reports` — *why*: spec Non-Goal —
   `--reconcile` output must stay byte-identical; relying on `index_found=False`
   to do this implicitly is fragile.
9. Add the tests, then run the Validation Commands — *why*: 37 tests pass on
   `dev` today; that number must only grow.

### `scripts/sdd/worktree_status.py` (MODIFY) — flow_type literal

```python
# occurrences: 1 (verified: grep -c 'flow_type: Literal\["feature", "hotfix"\]' scripts/sdd/worktree_status.py)
# REPLACE the line `    flow_type: Literal["feature", "hotfix"]` (verified: scripts/sdd/worktree_status.py:60)
    #: ``"non-sdd"`` marks a worktree under WORKTREE_ROOT whose branch is not an
    #: SDD branch: health only, no tasks, never ready_for_done (FEAT-582 §8).
    flow_type: Literal["feature", "hotfix", "non-sdd"]
```

**Why this shape**: `flow_type` becomes the single discriminator consumers key
on, instead of making `feature_slug`/`feature_id` optional (which would break
every f-string in `main()` and both lookup maps in `reconcile_reports`). Do NOT
reorder the literal members and do NOT rename them — `.claude/commands/sdd-status.md`
and the `/sdd-next` twins will key on the exact string `"non-sdd"`.

### `scripts/sdd/worktree_status.py` (MODIFY) — containment helper

```python
# occurrences: 1 (verified: grep -c 'def _parse_porcelain' scripts/sdd/worktree_status.py)
# BEFORE — insert above `def _parse_porcelain(output: str) -> list[tuple[Path, str | None]]:` (verified: scripts/sdd/worktree_status.py:215)
def _is_under_worktree_root(path: Path, worktree_root: Path) -> bool:
    """Return True when ``path`` is ``worktree_root`` itself or nested inside it.

    Both arguments must already be resolved — the caller resolves once and
    passes the result, so a symlinked ``.claude/worktrees`` cannot make this
    silently return False for every candidate.

    Args:
        path: A resolved worktree path.
        worktree_root: The resolved ``repo_root / WORKTREE_ROOT``.

    Returns:
        Whether ``path`` lives in the SDD worktree pool.
    """
    return path == worktree_root or worktree_root in path.parents
```

**Why**: named and separately testable, because it is the only thing standing
between the primary checkout and a self-referential row in its own panel.

### `scripts/sdd/worktree_status.py` (MODIFY) — resolved root + sorted iteration

```python
# occurrences: 1 (verified: grep -c 'worktree_root = repo_root / WORKTREE_ROOT' scripts/sdd/worktree_status.py)
# REPLACE the line `    worktree_root = repo_root / WORKTREE_ROOT` (verified: scripts/sdd/worktree_status.py:266)
    worktree_root = (repo_root / WORKTREE_ROOT).resolve()
```

```python
# occurrences: 1 (verified: grep -c 'for wt_path in all_worktree_paths:' scripts/sdd/worktree_status.py)
# REPLACE the line `    for wt_path in all_worktree_paths:` (verified: scripts/sdd/worktree_status.py:278)
    # Sorted, not set order: the output of a status tool must be screen-diffable
    # run to run (issue:f3dabdbe09a8).
    for wt_path in sorted(all_worktree_paths):
```

**Why**: `.resolve()` on the root keeps it symmetrical with the already-resolved
candidate paths. `sorted()` is a one-token fix for the nondeterminism.

### `scripts/sdd/worktree_status.py` (MODIFY) — pool guard + non-SDD emission

```python
# occurrences: 1 (verified: grep -c '        # Parse branch name' scripts/sdd/worktree_status.py)
# REPLACE the block at `        # Parse branch name` through `            continue`
# (verified: scripts/sdd/worktree_status.py:295-299) — i.e. the four lines:
#     # Parse branch name
#     parsed = _parse_branch(branch)
#     if parsed is None:
#         # Not an SDD branch
#         continue
        # sdd-coder pool sub-worktrees are task-level attempts nested inside a
        # feature worktree (FEAT-549), not worktrees in their own right. They
        # live UNDER WORKTREE_ROOT, so the containment guard below does not
        # exclude them, and _parse_branch() returns None for them exactly as it
        # does for a non-SDD branch — hence the explicit test here.
        if _POOL_SUB_WORKTREE_RE.search(branch):
            continue

        parsed = _parse_branch(branch)
        if parsed is None:
            # Non-SDD branch (chore-*, fix-*, a detached "HEAD", a branch whose
            # name does not match the SDD patterns). FEAT-582 §8 resolved these
            # to appear in the Worktrees panel, health only. Only those under
            # WORKTREE_ROOT qualify: the primary checkout is itself a porcelain
            # entry and must never report itself (issue:07b75dc7dfae).
            if not _is_under_worktree_root(wt_path, worktree_root):
                continue
            reports.append(
                WorktreeReport(
                    feature_slug=branch,
                    feature_id=None,
                    flow_type="non-sdd",
                    worktree_path=str(wt_path),
                    branch=branch,
                    base_branch="dev",
                    health=_check_health(wt_path, "dev"),
                    tasks=[],
                    index_found=False,
                    ready_for_done=False,
                )
            )
            continue
```

**Why this shape**: `feature_slug` carries the **branch name** rather than
becoming optional — that is exactly what the documented worked example prints
as the row title (`chore-ruff-config`), and it keeps every existing consumer
compiling. `base_branch="dev"` is a literal default, not a read value: there is
no index to read it from. `_check_health` is still called because health is the
entire point of the row.

### `scripts/sdd/worktree_status.py` (MODIFY) — sorted return

```python
# occurrences: 1 (verified: grep -c '^    return reports' scripts/sdd/worktree_status.py)
# REPLACE the line `    return reports` (verified: scripts/sdd/worktree_status.py:330)
    # Stable output contract: identical underlying state yields identical
    # --json array order and table row order (issue:f3dabdbe09a8).
    return sorted(reports, key=lambda r: (r.branch, r.worktree_path))
```

### `scripts/sdd/worktree_status.py` (MODIFY) — reconcile filter

```python
# occurrences: 1 (verified: grep -c 'by_feature_id = {r.feature_id: r for r in reports if r.feature_id}' scripts/sdd/worktree_status.py)
# REPLACE the two lines starting at `    by_feature_id = ...` (verified: scripts/sdd/worktree_status.py:497-498)
    # Non-SDD worktrees carry no per-spec index and never belong on the task
    # board (FEAT-582 §8: Worktrees panel only). Filter them explicitly rather
    # than relying on index_found=False to exclude them by accident.
    sdd_reports = [r for r in reports if r.flow_type != "non-sdd"]
    by_feature_id = {r.feature_id: r for r in sdd_reports if r.feature_id}
    by_slug = {r.feature_slug: r for r in sdd_reports}
```

```python
# occurrences: 1 (verified: grep -c '    for report in reports:' scripts/sdd/worktree_status.py)
# REPLACE the line `    for report in reports:` (verified: scripts/sdd/worktree_status.py:509)
    for report in sdd_reports:
```

**Why**: two edits, one intent — no non-SDD entry may reach a `ReconciledFeature`.

### `tests/sdd_scripts/test_worktree_status.py` (MODIFY) — multi-worktree helper

```python
# occurrences: 1 (verified: grep -c '^def _discover_with_fake_worktree' tests/sdd_scripts/test_worktree_status.py)
# AFTER — insert below the `_discover_with_fake_worktree` function body, before the
# `# TestParseBranch` banner comment (verified: tests/sdd_scripts/test_worktree_status.py:82-124)
def _discover_with_branches(
    tmp_path: Path,
    branches: list[str],
    *,
    status_out: str = "",
    log_out: str = "",
):
    """Run discover_worktree_reports over several fake worktrees at once.

    Every branch in ``branches`` gets a directory under
    ``tmp_path/.claude/worktrees/<branch-with-slashes-flattened>`` and a
    porcelain block. The primary checkout (``tmp_path`` itself, on ``dev``) is
    always included so tests can assert it is never self-reported.

    Returns the full report list, unfiltered.
    """
    # FILL IN: build worktree_root, one directory per branch, and the porcelain
    #   text — reuse the exact shape of _discover_with_fake_worktree above
    #   (same three patches: _git, WORKTREE_ROOT, _live_process_count).
    #   Bounded by: WORKTREE_ROOT must be patched with an ABSOLUTE str, and the
    #   first porcelain block must be `worktree {tmp_path}` on branch `dev`.
    raise NotImplementedError
```

**Why**: the existing helper builds exactly one worktree and filters to
`FEAT-550`, which cannot express "the primary checkout is absent", "pool
worktrees are absent" or "order is stable across ≥3 entries". Extend the
module's own idiom rather than importing a new fixture framework.

### `tests/sdd_scripts/test_worktree_status.py` (MODIFY) — new test class

```python
# occurrences: 1 (verified: grep -c '^class TestDiscover:' tests/sdd_scripts/test_worktree_status.py)
# AFTER — insert below the end of `class TestDiscover:` and before the `# TestCli`
# banner comment (verified: tests/sdd_scripts/test_worktree_status.py:331-349)
class TestNonSddWorktrees:
    """FEAT-619 / issue:07b75dc7dfae — non-SDD worktrees reach --json."""

    def test_non_sdd_branch_is_reported(self, tmp_path):
        """A chore-* worktree under WORKTREE_ROOT yields a health-only report."""
        # FILL IN: assert flow_type == "non-sdd", feature_slug == branch,
        #   feature_id is None, tasks == [], index_found is False,
        #   ready_for_done is False — bounded by AC1.
        raise NotImplementedError

    def test_primary_checkout_is_not_reported(self, tmp_path):
        """repo_root itself is a porcelain entry but must never self-report."""
        # FILL IN: assert no report has worktree_path == str(tmp_path)
        #   and no report has branch == "dev" — bounded by AC2.
        raise NotImplementedError

    def test_pool_sub_worktree_is_not_reported(self, tmp_path):
        """sdd-coder attempt worktrees stay out of the panel."""
        # FILL IN: use a branch ending
        #   "--TASK-3891-a1-4c8992efd3f44e8a81cc4f0c713c8677" placed UNDER
        #   WORKTREE_ROOT, assert it produces no report — bounded by AC3.
        raise NotImplementedError

    def test_sdd_worktree_still_reported_alongside(self, tmp_path, sample_index):
        """Adding non-SDD rows must not regress normal feature discovery."""
        # FILL IN: mixed scan, assert the FEAT-550 report still has
        #   flow_type == "feature" and its tasks — bounded by AC1 + AC11.
        raise NotImplementedError

    def test_order_is_deterministic(self, tmp_path):
        """Repeated scans of unchanged state return identical branch order."""
        # FILL IN: run _discover_with_branches twice over >=3 branches, assert
        #   the two [r.branch] lists are equal AND equal to their own sorted()
        #   — bounded by AC4.
        raise NotImplementedError

    def test_non_sdd_excluded_from_reconcile(self, tmp_path):
        """--reconcile output is unchanged by the presence of non-SDD rows."""
        # FILL IN: call reconcile_reports(tmp_path, sdd_only) and
        #   reconcile_reports(tmp_path, sdd_only + [non_sdd_report]) and assert
        #   the two results are equal — bounded by AC9. Build the non-SDD
        #   WorktreeReport directly (no discovery needed).
        raise NotImplementedError
```

**Why**: one class per ledger issue cluster keeps the suite navigable and makes
the `-k` selector in the Validation Commands meaningful.

### FILL IN checklist

- [ ] `_discover_with_branches` — porcelain/dir construction; bounded by: same
      three patches and absolute `WORKTREE_ROOT` as the existing helper.
- [ ] `TestNonSddWorktrees.test_non_sdd_branch_is_reported` — field assertions; AC1.
- [ ] `TestNonSddWorktrees.test_primary_checkout_is_not_reported` — AC2.
- [ ] `TestNonSddWorktrees.test_pool_sub_worktree_is_not_reported` — AC3.
- [ ] `TestNonSddWorktrees.test_sdd_worktree_still_reported_alongside` — AC1/AC11.
- [ ] `TestNonSddWorktrees.test_order_is_deterministic` — AC4.
- [ ] `TestNonSddWorktrees.test_non_sdd_excluded_from_reconcile` — AC9.

---

## Acceptance Criteria

- [ ] AC1 — A worktree under `WORKTREE_ROOT` whose branch does not parse as an
      SDD branch appears in `discover_worktree_reports` output with
      `flow_type: "non-sdd"`, `feature_id: None`, `tasks: []`,
      `index_found: False`, `ready_for_done: False`.
- [ ] AC2 — The primary checkout never appears in its own report list.
- [ ] AC3 — sdd-coder pool sub-worktrees never appear in the report list.
- [ ] AC4 — Report order is identical across repeated runs against unchanged
      state and equals `sorted(..., key=(branch, worktree_path))`.
- [ ] AC9 — `reconcile_reports` output is unaffected by non-SDD entries.
- [ ] AC11 — All pre-existing tests in the module still pass (37 on `dev` today).
- [ ] `ruff check scripts/sdd/worktree_status.py tests/sdd_scripts/test_worktree_status.py`
      is clean.
- [ ] Manual sanity check: `python -m scripts.sdd.worktree_status --json` on this
      checkout lists the real non-SDD worktrees (e.g. `chore-ruff-config`,
      `fix-codeql-pipeline`) and neither the primary checkout nor any `--pool/` entry.

---

## Validation Commands

- `pytest tests/sdd_scripts/test_worktree_status.py -q`
- `pytest tests/sdd_scripts/test_worktree_status.py::TestNonSddWorktrees -q`

---

## Test Specification

See the Implementation Blueprint's test blocks — `TestNonSddWorktrees` with six
cases, plus the `_discover_with_branches` helper. Reuse the module's existing
`_completed` helper and the `sample_index` / `all_done_index` fixtures; do not
introduce a `conftest.py`.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug sdd-worktree-status-tech-debt --feature-id FEAT-619`)
2. **Read the spec** at `sdd/specs/sdd-worktree-status-tech-debt.spec.md`
3. **Check dependencies** — none.
4. **Verify the Codebase Contract** — re-`grep` each anchor line and its
   occurrence count before editing; a count that no longer matches means the
   anchor moved, so re-locate it rather than inventing an attachment point.
5. **Update status** in `sdd/tasks/index/sdd-worktree-status-tech-debt.json` →
   `"in-progress"` (set `started_at`) and commit only that index file.
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`.
7. **Verify** all acceptance criteria — run the Validation Commands.
8. **Commit the code** — stage only the two files this task lists.
9. **Close the task** with
   `scripts/sdd/close_task.sh TASK-3915 sdd-worktree-status-tech-debt verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: Claude Opus 5 (`/sdd-fix issue:07b75dc7dfae`)
**Date**: 2026-10-01
**Notes**: Implemented exactly as blueprinted (flow_type literal,
`_is_under_worktree_root`, resolved root, sorted iteration + sorted return,
pool guard, non-SDD emission, reconcile filter), plus ONE unplanned guard
described below. 8 new tests in `TestNonSddWorktrees`, plus a
`_discover_with_branches` helper alongside the existing single-worktree one.
Suite: 37 → 45 passing; `ruff check` clean on both files.

**Deviations from spec**: one addition, no removals.

The blueprint's two guards (primary checkout by path containment, pool
sub-worktrees by `_POOL_SUB_WORKTREE_RE`) were necessary but NOT sufficient.
Running the new code against the real checkout produced **54 non-SDD rows, 35
of them on branch `dev`**. Cause: `discover_worktree_reports`' orphan scan adds
every *directory* under `WORKTREE_ROOT` that git does not know as a worktree —
including the sdd-coder `--pool` CONTAINER directories (17 of them here) and
leftover directories whose worktree was removed. For those, the `branch is
None` fallback runs `git rev-parse --abbrev-ref HEAD` with `cwd` inside the
directory; since `.claude/worktrees/` sits inside the primary checkout, git
walks UP and returns the primary checkout's branch, `dev`. That was harmless
before this task (`dev` never parsed as an SDD branch, so the row was dropped)
and became 35 bogus rows the moment unparseable branches started being emitted.

Fix: require `(wt_path / ".git").exists()` before the rev-parse fallback — a
real git worktree carries its own `.git` file, a bare directory does not. This
restores exactly the pre-task outcome for those directories (skipped) while
letting genuine non-SDD worktrees through. Covered by
`test_orphan_directory_without_git_is_not_reported`.

Verified against the live checkout: 32 reports, 19 non-SDD, matching
`git worktree list` exactly — no `--pool` rows, no primary-checkout row,
order equal to its own `sorted()`.

Note for later tasks: this does NOT make the orphan scan meaningful for
leftover directories — they are now simply skipped rather than mis-reported.
Surfacing them properly would need a different branch source than `rev-parse`
and is outside both this feature's spec and the ledger issues it drains.
