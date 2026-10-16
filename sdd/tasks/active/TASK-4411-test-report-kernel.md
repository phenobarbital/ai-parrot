# TASK-4411: Test-report kernel (`test_scope/report.py`)

**Feature**: FEAT-695 — sdd-done test-results table
**Spec**: `sdd/specs/sdd-done-tests.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This task implements spec §3 Module 1, the stdlib-only kernel every other task
imports. It does five things:
- injects a unique `--junitxml` per pytest invocation;
- parses junit into a `SuiteResult`;
- merges results into a per-task JSON record under a tmp report root;
- loads all records of a feature;
- renders the Markdown `## Tests` section that `/sdd-done` puts into the PR body.

Decisions it must honour:
- The re-run threshold is ≤ 10 tasks.
- Records live in tmp, never in the worktree.
- The kernel never blocks or changes an exit code.
- Retries count once (latest).
- Totals are labelled as per-task invocation sums.

---

## Scope

- Create `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py` with the dataclasses and functions in the blueprint.
- Create `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_report.py` covering the spec §4 kernel rows.

**NOT in scope**: wiring into `select_tests.py` (TASK-4412) or `background.py` (TASK-4413); the CLI (TASK-4414); `.md` command text (TASK-4415). Do NOT export from `test_scope/__init__.py`: callers import `test_scope.report` explicitly, so the package `__init__` stays untouched and never conflicts.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py` | CREATE | kernel |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_report.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.test_scope.datatypes import PytestInvocation  # verified: test_scope/datatypes.py:22
# inside the kernel use a RELATIVE import: `from .datatypes import PytestInvocation`
# (the package is also loaded by path as top-level `test_scope` — select_tests.py:_load_kernel line 20)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/datatypes.py:20-27
@dataclass(frozen=True)
class PytestInvocation:
    distribution: str              # "<dist>" or "root"
    argv: tuple[str, ...]          # full argv starting with "pytest"
    targets: tuple[TestTarget, ...]

# packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py:148 (reference only — do NOT import, it is not stdlib-only)
CLAUDE_SCRATCH_ROOT = Path("/tmp") / f"claude-{os.getuid()}"   # bound writable into the bwrap sandbox
```

### Does NOT Exist
- ~~`test_scope.report`~~ — this task creates it.
- ~~any junit handling in `test_scope/`~~ — none exists.
- ~~Pydantic in the kernel~~ — forbidden (`test_scope/__init__.py` docstring: stdlib-only; only `models.py` imports pydantic).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_report.py", "action": "CREATE"}
  ],
  "contract_symbols": ["sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/datatypes.py#PytestInvocation"]
}
```

---

## Implementation Notes

### Key Constraints
- Stdlib only: `dataclasses`, `json`, `os`, `fcntl` (guarded `try/except ImportError` like `sdd_coder/evidence.py`), `xml.etree.ElementTree`, `pathlib`, `datetime`, `tempfile`, `logging`.
- Recording is best-effort. Every write function catches `OSError` and logs a warning; nothing raises into a test run (spec AC7).
- Atomic publish = write a temp file in the same dir, then `os.replace`, under an `fcntl.flock` on `<task>.json.lock`.

---

## Implementation Blueprint

### Steps (in order)
1. Write the dataclasses and constants. *Why*: every other task imports these names verbatim (spec §2 Data Models).
2. Implement `report_root`, `junit_path_for`, `with_junit`. *Why*: one unique junit file per invocation (spec §9 S2).
3. Implement `parse_junit`. Sum all `<testsuite>` elements, whether the root is `<testsuites>` or `<testsuite>`. *Why*: xdist and plain runs differ in root shape.
4. Implement `append_suite` / `load_records`, with latest-wins per suite and `attempts += 1`. *Why*: retries must not double-count (AC13).
5. Implement `should_rerun` and `render_markdown`, then the tests.

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py` (CREATE)
```python
"""Structured pytest result recording for the SDD cycle (FEAT-695).

Stdlib-only, like the rest of the kernel. Records are a TEMPORARY artifact under
`report_root()`; never written into a worktree, never committed.
"""
from __future__ import annotations

import json
import logging
import os
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .datatypes import PytestInvocation

try:  # POSIX only
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

REPORT_ROOT_ENV = "SDD_TEST_REPORT_DIR"
RERUN_TASK_THRESHOLD = 10
RERUN_RECORD = "_rerun"
STATUSES = ("ok", "failed", "timed_out", "no_junit", "report_parse_error", "selection_error")


@dataclass(frozen=True)
class SuiteResult:
    suite: str
    tests: int
    passed: int
    failed: int
    errors: int
    skipped: int
    duration_s: float
    exit_code: int
    argv: tuple[str, ...]
    status: str


@dataclass(frozen=True)
class TaskTestRecord:
    feature_id: str
    task_id: str
    head_sha: str
    base_ref: str
    tier: str
    source: str
    recorded_at: str
    attempts: int
    suites: tuple[SuiteResult, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)


def report_root() -> Path:
    """$SDD_TEST_REPORT_DIR, else /tmp/claude-<uid>/sdd-tests (bound into the bwrap sandbox)."""
    # FILL IN: env override, else Path("/tmp") / f"claude-{os.getuid()}" / "sdd-tests" — bounded by spec §7 bwrap gotcha


def junit_path_for(feature_id: str, task_id: str, suite: str, ordinal: int) -> Path:
    """<root>/<feature>/junit/<task>--<suite>--<ordinal>.xml — unique per invocation."""


def with_junit(invocation: PytestInvocation, junit_path: Path) -> tuple[str, ...]:
    """Return a NEW argv with --junitxml=<junit_path>; never mutates invocation.argv."""
    return (*invocation.argv, f"--junitxml={junit_path}")


def parse_junit(junit_path: Path, *, suite: str, argv: tuple[str, ...], exit_code: int,
                duration_s: float, timed_out: bool = False) -> SuiteResult:
    """Sum <testsuite> counters. Missing file -> 'no_junit'; bad XML -> 'report_parse_error'; never raises."""
    # FILL IN: passed = tests - failures - errors - skipped; status precedence timed_out > no_junit/parse_error > failed (exit!=0 or failed+errors>0) > ok


def append_suite(feature_id: str, task_id: str, result: SuiteResult, *, head_sha: str, base_ref: str,
                 tier: str, source: str, note: str | None = None) -> Path | None:
    """Merge into <root>/<feature>/<task>.json: same suite replaced, attempts+1; atomic + flock; None on OSError.

    NOTE: head_sha/tier/source are record-level (last-write-wins). When suites within one task run at
    different commits (rare, during retries), the staleness check uses the last append's SHA. This is
    acceptable: a single task normally runs all suites at one commit."""


def load_records(feature_id: str) -> tuple[dict[str, TaskTestRecord], list[str]]:
    """All records of a feature keyed by task id, plus notes naming corrupt files that were skipped."""


def should_rerun(task_count: int) -> bool:
    """Deterministic closeout rule (spec AC3): task_count <= RERUN_TASK_THRESHOLD."""
    return task_count <= RERUN_TASK_THRESHOLD


def render_markdown(records: dict[str, TaskTestRecord], task_ids: list[str], *, final_head: str,
                    rerun: TaskTestRecord | None, rerun_skip_reason: str | None,
                    notes: tuple[str, ...] = ()) -> str:
    """'## Tests' section: per-suite aggregate rows + Total + optional re-run column + <details> per task."""
    # FILL IN: table columns Suite|Tests|Passed|Failed|Skipped|Errors|Duration[|Final HEAD re-run];
    #          ❌ when status != "ok" (covers timed_out/no_junit/report_parse_error with 0 counts) OR failed+errors>0;
    #          Total label per AC13; "re-run skipped (<reason>)" line; per-task rows mark "stale" (head_sha != final_head) / "no data";
    #          if rerun and rerun.head_sha != final_head, mark the re-run column as "stale";
    #          if notes, append a "### Notes" subsection listing each corrupt-record note
```
**Why this shape**: these names and signatures are the contract that TASK-4412/4413/4414 call. Do not rename them. `load_records` returns notes so the renderer can surface corrupt files instead of hiding them. `render_markdown` accepts `notes` explicitly so the CLI (TASK-4414) passes them through — discarding them silently was a design bug (issue:5b33290f55c9).

### `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_report.py` (CREATE)
```python
"""Tests for the FEAT-695 test-report kernel."""
from __future__ import annotations

import pytest

from parrot.flows.dev_loop.test_scope import report


@pytest.fixture(autouse=True)
def _root(tmp_path, monkeypatch):
    monkeypatch.setenv(report.REPORT_ROOT_ENV, str(tmp_path / "root"))


# FILL IN: one test per spec §4 kernel row (with_junit/parse_junit x4/append_suite x2/report_root/should_rerun/render x6)
```

### FILL IN checklist
- [ ] `report_root` env/default — spec §7
- [ ] `parse_junit` counting + status precedence — AC7, §9 S7
- [ ] `append_suite` latest-wins + attempts + atomic/flock — AC13; document last-write-wins for record-level metadata
- [ ] `render_markdown` ❌ = `status != "ok"` OR `failed+errors>0` — a timed_out/no_junit/report_parse_error suite with 0 counts must still show ❌ (issue:5b33290f55c9)
- [ ] `render_markdown` table, Total label, stale/no-data, re-run column/skip line — AC4/AC5/AC13
- [ ] `render_markdown` notes: append "### Notes" subsection with corrupt-record notes when non-empty (issue:5b33290f55c9)
- [ ] `render_markdown` rerun staleness: if `rerun.head_sha != final_head`, mark the re-run column as stale (issue:5b33290f55c9)
- [ ] tests for every kernel row in spec §4, including concurrent append (two `multiprocessing` processes)
- [ ] test: timed_out suite with 0 tests/0 failed renders ❌ not ✅ (issue:5b33290f55c9)

---

## Acceptance Criteria
- [ ] Spec AC7, AC8, AC9, AC13 hold at kernel level.
- [ ] `python -c "import sys; sys.path.insert(0,'packages/ai-parrot/src/parrot/flows/dev_loop'); import test_scope.report"` works (path import, no `parrot`).
- [ ] `ruff check` clean on both files.

## Validation Commands
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_report.py -q`

---

## Agent Instructions
Follow `sdd/templates/task.md` § Agent Instructions: work in the feature worktree, verify the contract, implement from the blueprint, run the Validation Commands, commit only the listed files, and close with `scripts/sdd/close_task.sh TASK-4411 sdd-done-tests verified`.

---

## Completion Note
*(Agent fills this in when done)*
