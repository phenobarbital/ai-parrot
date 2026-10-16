# TASK-4414: `scripts/sdd/test_report.py` CLI (`decide-rerun`, `render`)

**Feature**: FEAT-695 — sdd-done test-results table
**Spec**: `sdd/specs/sdd-done-tests.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4411
**Assigned-to**: unassigned
**Discovered-from**: `issue:326c8c0da36c`

---

## Context

This task implements spec §3 Module 4: the deterministic entry points `/sdd-done` calls. The
re-run decision is `len(index["tasks"]) <= 10` (AC3). Both subcommands are **fail-open**: they exit 0
even with red suites, no records, an unreadable index or an unwritable `--out` (AC6, spec §3 Module 4
"Fail-open contract"). `/sdd-done` §4.7 calls them unconditionally and must still open the PR, so a
non-zero exit or empty output here would block a closeout — `issue:326c8c0da36c`.

---

## Scope

- Create `scripts/sdd/test_report.py`. Load the kernel by path, mirroring `select_tests.py:_load_kernel` (never `import parrot`).
- `decide-rerun --index <idx>` prints `rerun`, or `skip (<N> tasks > 10)`, and exits 0.
- `render --index <idx> [--worktree <wt>] [--out <file>]`:
  - read `feature_id` and task ids from the index;
  - load the records;
  - take the final HEAD from `git -C <wt> rev-parse HEAD`;
  - pass the `_rerun` record if present, else the skip reason;
  - write the Markdown to stdout or `--out`; exit 0.
- **Fail-open paths (`issue:326c8c0da36c`)** — never a non-zero exit, never silent:
  - index missing / unreadable / not valid JSON / no `feature_id`: `decide-rerun` prints
    `skip (index unreadable)`; `render` emits a minimal section
    (`## Tests` + `_No test data recorded for this feature._`) to the same destination. Both exit 0.
  - `--out` raises `OSError`: log a one-line warning to stderr, write the same Markdown to stdout
    instead, and still exit 0 (the caller guards on a non-empty file).
  - the only non-zero exit left is argparse's own usage exit for an unknown subcommand/flag.
- Create `tests/sdd_scripts/test_test_report.py`.

**NOT in scope**: rendering logic (TASK-4411 owns `render_markdown`); `.md` command text.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/test_report.py` | CREATE | CLI |
| `tests/sdd_scripts/test_test_report.py` | CREATE | CLI tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Pattern to mirror — scripts/sdd/select_tests.py:18-27
_KERNEL_PARENT = Path(__file__).resolve().parents[2] / "packages/ai-parrot/src/parrot/flows/dev_loop"
def _load_kernel() -> ModuleType: ...   # inserts _KERNEL_PARENT on sys.path, `import test_scope`
# then: import test_scope.report as report_mod  # noqa: PLC0415
```

### Existing Signatures to Use
```python
# test_scope/report.py (TASK-4411)
should_rerun(task_count: int) -> bool
load_records(feature_id: str) -> tuple[dict[str, TaskTestRecord], list[str]]
render_markdown(records, task_ids, *, final_head, rerun, rerun_skip_reason) -> str
RERUN_RECORD = "_rerun"; RERUN_TASK_THRESHOLD = 10
# per-spec index shape: {"feature_id": "FEAT-695", "tasks": [{"id": "TASK-4411", ...}, ...]}  (sdd/tasks/index/sdd-done-tests.json)
```

### Does NOT Exist
- ~~`scripts/sdd/test_report.py`~~ — created here.
- ~~a `--threshold` flag~~ — the threshold is the kernel constant; do not make it configurable (deterministic rule).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "scripts/sdd/test_report.py", "action": "CREATE"},
    {"path": "tests/sdd_scripts/test_test_report.py", "action": "CREATE"}
  ],
  "contract_symbols": ["sym:scripts/sdd/select_tests.py#_load_kernel"]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Copy the `_load_kernel` pattern. *Why*: the script must run under the system python native hook without `import parrot`.
2. Add an argparse with two subparsers. *Why*: TASK-4415 writes these exact command lines into `/sdd-done`.

### `scripts/sdd/test_report.py` (CREATE)
```python
#!/usr/bin/env python3
"""FEAT-695: decide the /sdd-done closeout re-run and render the PR '## Tests' section.

    python -m scripts.sdd.test_report decide-rerun --index sdd/tasks/index/<slug>.json
    python -m scripts.sdd.test_report render --index <idx> [--worktree <wt>] [--out <file>]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

_KERNEL_PARENT = Path(__file__).resolve().parents[2] / "packages/ai-parrot/src/parrot/flows/dev_loop"


def _load_report() -> ModuleType:
    """Import `test_scope.report` by path (never `import parrot`)."""
    if str(_KERNEL_PARENT) not in sys.path:
        sys.path.insert(0, str(_KERNEL_PARENT))
    import test_scope.report as report_mod  # noqa: PLC0415 — path-dependent import

    return report_mod


def main(argv: list[str] | None = None) -> int:
    """Always 0 — red tests, no data, an unreadable index and an unwritable --out all exit 0.

    Only argparse's own usage error (unknown subcommand/flag) leaves a non-zero code.
    """
    # FILL IN: subparsers decide-rerun/render; output "rerun" | f"skip ({n} tasks > {report.RERUN_TASK_THRESHOLD})"
    # FILL IN: render → records, notes = load_records(feature_id); final_head via git rev-parse (fallback "unknown")


if __name__ == "__main__":
    raise SystemExit(main())
```

### FILL IN checklist
- [ ] `decide-rerun` output format exactly `rerun` / `skip (<N> tasks > 10)` — AC3
- [ ] `render` exits 0 with missing records ("no data") and red suites — AC6
- [ ] `decide-rerun` on an unreadable index prints `skip (index unreadable)` and exits 0 — AC6
- [ ] `render` on an unreadable index emits the minimal `## Tests` + `_No test data recorded for this feature._` and exits 0 — AC6
- [ ] an `OSError` from `--out` warns on stderr, falls back to stdout, exits 0 — AC6
- [ ] tests: `test_decide_rerun_cli` (10 → rerun, 11 → skip), render with a fixture record, `test_decide_rerun_unreadable_index`, `test_render_unreadable_index_exits_zero`, `test_render_out_oserror_falls_back_to_stdout` (set `SDD_TEST_REPORT_DIR` to tmp)

---

## Acceptance Criteria
- [ ] Spec AC3 and AC6 hold for the CLI.
- [ ] No input makes either subcommand exit non-zero except an argparse usage error, and `render` always writes
      a `## Tests` section somewhere (file or stdout) — `issue:326c8c0da36c`.
- [ ] `ruff check scripts/sdd/test_report.py` is clean.

## Validation Commands
- `pytest tests/sdd_scripts/test_test_report.py -q`

---

## Agent Instructions
Follow `sdd/templates/task.md` § Agent Instructions. Close with `scripts/sdd/close_task.sh TASK-4414 sdd-done-tests verified`.

---

## Completion Note

- Task: TASK-4414
- Feature: sdd-done-tests
- Implementation SHA: a343bee8b9fccd25d27c5364f83676a982364fb6
- Closed at (UTC): 2026-10-16T01:26:10+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 92.1s · Tokens: n/a |
