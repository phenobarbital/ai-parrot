# TASK-3917: De-duplicate the CLI table, render unknown health, fix the WORKTREE_ROOT anchor

**Feature**: FEAT-619 — worktree_status Tech-Debt Drain (FEAT-582 follow-up)
**Spec**: `sdd/specs/sdd-worktree-status-tech-debt.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3916
**Assigned-to**: unassigned

---

## Context

Implements spec Module 3. Closes the group's two nitpick issues and finishes
the user-visible half of the two earlier tasks:

- `issue:4456385c283c` (low) — `main()`'s plain-table printer folds
  `feature_id` into the Name column (`f"{slug} ({feature_id})"`) **and** prints
  it again in the dedicated Feature column. Not incorrect — FEAT-582's AC3 only
  required the columns to be present — just redundant.
- `issue:0974a2a92df3` (low) — the import comment
  `from scripts.sdd.sdd_meta import WORKTREE_ROOT  # verified: scripts/sdd/sdd_meta.py:15`
  is technically true but misleading: `scripts/sdd/sdd_meta.py` is a
  compatibility shim and its line 15 is an entry in an import list, not a
  definition. `WORKTREE_ROOT` is actually defined at
  `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py:322`.

It also renders what TASK-3915 and TASK-3916 added: the `(non-SDD)` marker for
`flow_type == "non-sdd"` rows, and an `unknown` health token so the table never
shows a bare `clean` for a worktree whose state could not be read.

Depends on TASK-3916 because all three tasks modify
`scripts/sdd/worktree_status.py` and `tests/sdd_scripts/test_worktree_status.py`,
and because the `dirty_unknown`/`unpushed_unknown` attributes this task renders
do not exist until TASK-3916 lands.

---

## Scope

- Name column prints `feature_slug` alone, with `" (non-SDD)"` appended when
  `flow_type == "non-sdd"`; the Feature column keeps printing
  `r.feature_id or '-'`, so the id appears exactly once per row.
- Health column renders the unknown state instead of `clean` when
  `dirty_unknown` / `unpushed_unknown` is set.
- Correct the `WORKTREE_ROOT` import comment to name the defining file and line.
- Write tests for the table output.

**NOT in scope**:
- The `--reconcile` table (`main()`'s first branch) — untouched; its columns
  are `Feature / Id / Tasks / Source` and carry no duplication.
- `--json` output shape — unchanged by this task.
- Adding, removing or reordering table columns; changing column widths beyond
  what the content requires.
- Documentation twins — TASK-3918.
- Any further change to `WorktreeHealth`, discovery or reconciliation.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/worktree_status.py` | MODIFY | Import comment, Name column, health column |
| `tests/sdd_scripts/test_worktree_status.py` | MODIFY | CLI table rendering tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from scripts.sdd.worktree_status import (     # verified: tests/sdd_scripts/test_worktree_status.py:13-27
    WorktreeHealth,
    WorktreeReport,
    WorktreeTaskStatus,
    main,
)
```

### Existing Signatures to Use

```python
# scripts/sdd/worktree_status.py — line 20, the comment this task corrects:
from scripts.sdd.sdd_meta import WORKTREE_ROOT  # verified: scripts/sdd/sdd_meta.py:15

# main() plain-table branch (verified: scripts/sdd/worktree_status.py:582-613)
#   header (line 584):
#     print(f"{'Name':<40} {'Branch':<30} {'Feature':<15} {'Tasks':<12} {'Health':<20} {'Ready'}")
#   name   (lines 588-590):  name = r.feature_slug ; if r.feature_id: name = f"{r.feature_slug} ({r.feature_id})"
#   health (lines 601-608):  health_parts list -> ", ".join(health_parts) if health_parts else "clean"
#   row    (line 613):
#     print(f"{name:<40} {branch:<30} {r.feature_id or '-':<15} {tasks_str:<12} {health_str:<20} {ready_str}")

def main() -> int:   # line 522 — flags are exactly --json and --reconcile
```

```python
# After TASK-3915 and TASK-3916 these exist (re-verify before editing):
class WorktreeReport(BaseModel):
    flow_type: Literal["feature", "hotfix", "non-sdd"]
class WorktreeHealth(BaseModel):
    dirty_unknown: bool = False
    unpushed_unknown: bool = False
```

```python
# tests/sdd_scripts/test_worktree_status.py
class TestCli:   # line 355 — existing CLI tests; follow their capsys/monkeypatch idiom
```

### Does NOT Exist

- ~~A `--table` or `--format` flag~~ — `main()` has exactly `--json` and
  `--reconcile`.
- ~~`rich`, `tabulate` or any table library~~ — the table is hand-rolled
  f-string padding. Do not introduce a dependency.
- ~~`WorktreeReport.display_name`~~ — compute the name inline as today.
- ~~A logger in this module~~ — output is `print`; this is a CLI script, and
  the repo's no-`print` rule is about library code, not this entry point.

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
    "sym:scripts/sdd/worktree_status.py#main",
    "sym:scripts/sdd/worktree_status.py#WorktreeReport",
    "sym:scripts/sdd/worktree_status.py#WorktreeHealth"
  ]
}
```

---

## Implementation Notes

### Column widths

`Name` is `<40` and `Branch` is `<30`. A non-SDD row's name is its branch plus
`" (non-SDD)"` — 10 extra characters. Branches in this checkout reach ~45
characters (`feat-FEAT-551-msteams-formdesigner-renderer`), so a long non-SDD
name will overflow its column and push the row. That is the existing behaviour
for long SDD slugs too (f-string padding never truncates), so **do not add
truncation** — it would be a scope change and would hide information in a tool
whose job is to show it.

### Health token

Keep the existing `health_parts` list idiom. An unknown signal is a part like
any other, so the `else "clean"` fallback is reached only when nothing at all
is flagged — which is exactly the fix: a worktree with an unreadable status can
no longer fall through to `clean`.

---

## Implementation Blueprint

### Steps (in order)

1. Fix the import comment — *why*: one line, no behaviour, and it is the whole
   of `issue:0974a2a92df3`.
2. Drop the `feature_id` interpolation from the Name column and add the
   `(non-SDD)` marker — *why*: the Feature column already prints the id, and the
   marker is what `.claude/commands/sdd-status.md`'s worked example shows.
3. Add the two unknown tokens to `health_parts` — *why*: without this the table
   still prints `clean` for a worktree TASK-3916 just marked unreadable, which
   would leave `issue:6b0b91e1f5b2` half-fixed at the surface the user reads.
4. Add tests, run the Validation Commands.

### `scripts/sdd/worktree_status.py` (MODIFY) — import comment

```python
# occurrences: 1 (verified: grep -c 'from scripts.sdd.sdd_meta import WORKTREE_ROOT' scripts/sdd/worktree_status.py)
# REPLACE the line `from scripts.sdd.sdd_meta import WORKTREE_ROOT  # verified: scripts/sdd/sdd_meta.py:15`
# (verified: scripts/sdd/worktree_status.py:20)
# scripts/sdd/sdd_meta.py is a re-export shim; the definition lives in the package.
from scripts.sdd.sdd_meta import (  # verified: packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py:322
    WORKTREE_ROOT,
)
```

**Why**: points a future reader at the real definition instead of at an entry in
the shim's import list. If the single-line form fits inside 120 columns after
you write it, a single-line import with the corrected trailing comment is
equally acceptable — the requirement is the anchor, not the formatting.

### `scripts/sdd/worktree_status.py` (MODIFY) — Name column

```python
# occurrences: 1 (verified: grep -c 'name = f"{r.feature_slug} ({r.feature_id})"' scripts/sdd/worktree_status.py)
# REPLACE the block `            # Name: feature_slug` through
# `                name = f"{r.feature_slug} ({r.feature_id})"`
# (verified: scripts/sdd/worktree_status.py:587-590) — i.e. the four lines:
#     # Name: feature_slug
#     name = r.feature_slug
#     if r.feature_id:
#         name = f"{r.feature_slug} ({r.feature_id})"
            # Name: feature_slug only — the Feature column below already prints
            # feature_id, and printing it twice was issue:4456385c283c.
            name = r.feature_slug
            if r.flow_type == "non-sdd":
                name = f"{r.feature_slug} (non-SDD)"
```

**Why**: matches the documented worked example row
(`chore-ruff-config  (non-SDD)`) exactly, and leaves the id to its own column.

### `scripts/sdd/worktree_status.py` (MODIFY) — health column

```python
# occurrences: 1 (verified: grep -c 'health_str = ", ".join(health_parts) if health_parts else "clean"' scripts/sdd/worktree_status.py)
# BEFORE — insert above `            health_str = ", ".join(health_parts) if health_parts else "clean"`
# (verified: scripts/sdd/worktree_status.py:608)
            # An unreadable signal is its own token, so the "clean" fallback is
            # reached only when nothing at all is flagged (issue:6b0b91e1f5b2).
            if r.health.dirty_unknown:
                health_parts.append("dirty:unknown")
            if r.health.unpushed_unknown:
                health_parts.append("unpushed:unknown")
```

**Why**: appending to the existing list means ordering, joining and the
fallback all stay exactly as they were; only the set of possible parts grows.

### `tests/sdd_scripts/test_worktree_status.py` (MODIFY) — CLI tests

```python
# occurrences: 1 (verified: grep -c '^class TestCli:' tests/sdd_scripts/test_worktree_status.py)
# AFTER — append as new methods at the end of `class TestCli`
# (verified: tests/sdd_scripts/test_worktree_status.py:355)
    def test_feature_id_printed_once_per_row(self, capsys):
        """The Name column no longer repeats feature_id (issue:4456385c283c)."""
        # FILL IN: drive main() with --json absent over a patched
        #   discover_worktree_reports returning one feature report with
        #   feature_id="FEAT-550"; assert the row line contains "FEAT-550"
        #   exactly once — bounded by AC7. Follow the existing TestCli idiom for
        #   patching argv/discovery and capturing stdout.
        raise NotImplementedError

    def test_non_sdd_row_is_marked_and_has_no_tasks(self, capsys):
        """A non-SDD row shows the marker and a 0/0 task count."""
        # FILL IN: one WorktreeReport(flow_type="non-sdd", feature_id=None,
        #   tasks=[]); assert "(non-SDD)" appears in its row and the Feature
        #   column shows "-" — bounded by AC1 + AC7.
        raise NotImplementedError

    def test_unknown_health_is_not_rendered_as_clean(self, capsys):
        """dirty_unknown/unpushed_unknown surface in the Health column."""
        # FILL IN: a report whose health has dirty_unknown=True; assert the row
        #   contains "unknown" and does NOT contain "clean" — bounded by AC5.
        raise NotImplementedError
```

### FILL IN checklist

- [ ] `TestCli.test_feature_id_printed_once_per_row` — AC7.
- [ ] `TestCli.test_non_sdd_row_is_marked_and_has_no_tasks` — AC1/AC7.
- [ ] `TestCli.test_unknown_health_is_not_rendered_as_clean` — AC5.

---

## Acceptance Criteria

- [ ] AC7 — Each plain-table row prints `feature_id` exactly once.
- [ ] AC8 — The `WORKTREE_ROOT` import comment names the defining file and line
      (`packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py:322`).
- [ ] AC1 (surface) — A `flow_type == "non-sdd"` row renders with the
      `(non-SDD)` marker and no task counts.
- [ ] AC5 (surface) — A row with `dirty_unknown` or `unpushed_unknown` renders
      an `unknown` token and never a bare `clean`.
- [ ] AC11 — All pre-existing tests still pass.
- [ ] `ruff check scripts/sdd/worktree_status.py tests/sdd_scripts/test_worktree_status.py`
      is clean.
- [ ] Manual sanity check: `python -m scripts.sdd.worktree_status` on this
      checkout prints one `FEAT-NNN` per row and marks the non-SDD worktrees.

---

## Validation Commands

- `pytest tests/sdd_scripts/test_worktree_status.py -q`
- `pytest tests/sdd_scripts/test_worktree_status.py::TestCli -q`

---

## Test Specification

See the Implementation Blueprint's test block: three new `TestCli` methods
following the existing class's patching and `capsys` idiom.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug sdd-worktree-status-tech-debt --feature-id FEAT-619`)
2. **Read the spec** at `sdd/specs/sdd-worktree-status-tech-debt.spec.md`
3. **Check dependencies** — TASK-3916 must be `"done"` in the per-spec index
   (and TASK-3915 before it). Both edit the same two files, so every line
   number in this task's anchors is pre-TASK-3915 and WILL have shifted:
   re-`grep` each anchor and its occurrence count before editing.
4. **Verify the Codebase Contract** — in particular that
   `WorktreeHealth.dirty_unknown` and `flow_type == "non-sdd"` now exist.
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`)
   and commit only that index file.
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`.
7. **Verify** all acceptance criteria — run the Validation Commands.
8. **Commit the code** — stage only the two files this task lists.
9. **Close the task** with
   `scripts/sdd/close_task.sh TASK-3917 sdd-worktree-status-tech-debt verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: Claude Opus 5 (`/sdd-fix issue:07b75dc7dfae`)
**Date**: 2026-10-01
**Notes**: Implemented exactly as blueprinted. 3 new `TestCli` methods plus a
`_run_table` helper on that class. Suite: 53 → 56 passing; `ruff check` clean.
The multi-line import form was used (the single-line form with the corrected
trailing comment exceeded 120 columns).

One blueprint assertion was wrong and was corrected during implementation, not
the code: `test_feature_id_printed_once_per_row` first asserted
`row.count("FEAT-550") == 1` over the WHOLE row, which fails at 2 — because the
**Branch** column legitimately contains `feat-FEAT-550-token-budget-bedrock`.
`issue:4456385c283c` is about the Name column duplicating the Feature column,
not about the branch. The assertion now targets the Name column (the first 40
characters, the f-string width): it must equal the slug and must not contain
the id, while the id must appear later in the row.

Verified by rendering the real checkout's table: 32 rows, each with exactly one
`FEAT-NNN` in its Feature column, 19 rows marked ` (non-SDD)` with `-` for
Feature and `0/0` tasks, and live `dirty:N, unpushed:N, live:N` health strings.

Known, deliberately unchanged: names longer than the 40-column Name field
overflow and push the row (e.g.
`fix/98205ecd666b-remove-extracted-finance-tests (non-SDD)`). This is the
pre-existing f-string padding behaviour for long SDD slugs too; adding
truncation would hide information in a tool whose job is to show it, and was
listed as out of scope.

**Deviations from spec**: none.
