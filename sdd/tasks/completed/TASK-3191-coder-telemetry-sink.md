# TASK-3191: Telemetry rows, durable-root resolution and the append-only sink

**Feature**: FEAT-554 — Empirical Token-Budget Sizing for sdd-coder Bedrock Seats
**Spec**: `sdd/specs/sdd-coder-bedrock-token-telemetry.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4, first file, and the resolutions of §10 R5/R6/R7 plus the
closing size note. This is the persistence layer: the two row shapes, the
allowlisted projection that keeps exception text out of the dataset, the
validated durable root, and a writer whose failures can never affect a dispatch.

It is a new standalone module, so it is safely parallel with the ledger and
transport tasks.

---

## Scope

- Create `parrot/flows/dev_loop/sdd_coder/telemetry.py` with `MAX_LINE_BYTES`,
  `AttemptUsageRow`, `OutcomeRow`, `feature_file_name`, `resolve_durable_root`,
  `build_attempt_row` and `CoderTelemetrySink`.
- Write unit tests for the row types, the root validation, the size bound and
  concurrent appends.

**NOT in scope**: calling any of it (TASK-3193), `AttemptRecord`'s new fields
(TASK-3192 — import it, do not change it), the analysis script (TASK-3194).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py` | CREATE | Rows, root resolution, sink |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_telemetry.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.sdd_coder.models import AttemptRecord  # verified: parrot/flows/dev_loop/sdd_coder/models.py:115
from parrot import conf                                          # verified: parrot/flows/dev_loop/sdd_coder/roster.py:9
from pydantic import BaseModel, Field
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py
class AttemptRecord(BaseModel):                                       # line 115
    attempt: int = Field(..., ge=1, le=3)                             # line 116
    seat_label: str                                                   # line 117
    backend: str = ""                                                 # line 118
    model: str = ""                                                   # line 119
    started_at: str                                                   # line 120
    ended_at: str = ""                                                # line 121
    duration_s: float = 0.0                                           # line 122
    usage: Dict[str, Any] = Field(default_factory=dict)               # line 125
    error: str = ""                                                   # line 126  <-- FULL exception string; NEVER persist
#   TASK-3192 adds: attempt_uid, job_id, resolved_model, turns, terminal,
#   error_class, declared_files, declared_files_known,
#   turns_with_unknown_usage, turn_series, budget_report

# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py
self._base_path = os.path.realpath(worktree_base_path or conf.WORKTREE_BASE_PATH)  # line 162
if not (wt == self._base_path or wt.startswith(self._base_path + os.sep)):          # line 193
    raise CoderFailure("worktree_outside_base", ...)                                # line 194
async def _journal(self, worktree: str, job: CoderJob) -> None:                     # line 472
    def _write() -> None: ...                                                       # line 482
    await asyncio.to_thread(_write)                                                 # line 488  <-- the S11 sync-I/O pattern

# packages/ai-parrot/src/parrot/conf.py
SDD_CODER_TELEMETRY_DIR: str  # added by TASK-3190; "" means "derive the main checkout"
WORKTREE_BASE_PATH: str                                                             # line 829
```

### Does NOT Exist
- ~~`parrot.flows.dev_loop.sdd_coder.telemetry`~~ — this task creates it.
- ~~`conf.BASE_DIR` as a usable durable root~~ — `BASE_DIR` comes from navconfig, which
  resolves `SITE_ROOT`, else an explicit `BASE_DIR`, else a virtualenv's parent, else a
  project-root search (`navconfig/project.py:129-161`). It is NOT the git main checkout,
  so a feature checkout with its own virtualenv resolves it *inside* the worktree
  `/sdd-done` deletes (spec §10 R7). Never use it here.
- ~~`SddCoderEngine.repo_root` / `.main_checkout`~~ — the engine knows only `_base_path`.
- ~~`fcntl.flock` on the JSONL~~ — not needed and not wanted: a single `os.write` to an
  `O_APPEND` fd is atomic with respect to other appenders on a regular file. Do not add
  locking.
- ~~`PIPE_BUF` mattering here~~ — 4096 governs pipes, not regular files. The 8192 budget
  exists to keep a row one bounded syscall and to fail loudly if rows grow.
- ~~`AttemptRecord.error_class` existing today~~ — TASK-3192 adds it. Until then this
  module must tolerate its absence when run against an un-migrated record.

---

## Implementation Notes

### Key Constraints
- **Allowlist, never dump.** `build_attempt_row` names every field it copies.
  `AttemptRecord.error` (full exception string) and `TaskResult.diagnostics`
  (raw merge output) must never appear in a row. A future field added to
  `AttemptRecord` must NOT leak into the dataset by default.
- **Never raise.** Every sink method logs and returns on failure. An unwritable
  root, an oversized row and a serialization error are all non-events for the
  caller (AC-11).
- Sync I/O goes through `asyncio.to_thread`, matching `_journal` (`engine.py:488`).
- One `os.write` of one pre-serialized line per row. No read-modify-write, no
  truncation of an oversized row into invalid JSON — drop it and log.
- `calibration_eligible` is computed in one place only: here, as
  `accounting_complete and turns_with_unknown_usage == 0`.

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:472-488` —
  the `asyncio.to_thread` write pattern to mirror.
- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:193-194` —
  the containment check whose reasoning `resolve_durable_root` reuses.

---

## Implementation Blueprint

### Steps (in order)
1. Write the two row models first — *why*: TASK-3193 and TASK-3194 both bind to this schema, so it must be settled before anything consumes it.
2. Write `feature_file_name` and `resolve_durable_root` — *why*: a bad root or a path-traversing feature id must fail at startup, not at the first write.
3. Write `build_attempt_row` as an explicit field-by-field projection — *why*: the allowlist is the privacy guarantee (AC-7); a `model_dump()` shortcut would defeat it.
4. Write the sink last — *why*: it is the only part with I/O, and it needs the size bound the rows determine.
5. Add the tests, including two concurrent writers — *why*: AC-10's interleaving claim cannot be verified by reading.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py` (CREATE — part 1: rows)
```python
"""Durable per-attempt token telemetry for sdd-coder (FEAT-554).

Two append-only JSONL line kinds per attempt, joined on `attempt_uid`:
an `attempt` row written when the attempt returns, and one or more `outcome`
rows written as the attempt's fate is decided. Rows carry counters, ids and
timings ONLY — never prompt text, tool arguments or exception messages
(spec §10 R5).
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field

from parrot.flows.dev_loop.sdd_coder.models import AttemptRecord

logger = logging.getLogger(__name__)

MAX_LINE_BYTES: int = 8192
"""Upper bound for one serialized row, checked at write time.

Measured worst case with every string field at `max_length` and a full
101-turn series: ~3.6 KB (probe, 2026-09-12 —
artifacts/logs/feat554-row-size-probe-20260912.md). NOT a PIPE_BUF
requirement: 4096 governs pipes, not regular files, and POSIX makes an
`O_APPEND` write to a regular file atomic against other appenders at any
size. The budget keeps each row one bounded syscall and fails loudly if a
row ever grows unexpectedly.
"""

_SAFE_FEATURE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class AttemptUsageRow(BaseModel):
    """The `attempt` JSONL line. See spec §2 Data Models for the field list."""

    kind: Literal["attempt"] = "attempt"
    ts: str
    attempt_uid: str = Field(..., min_length=8, max_length=64)
    job_id: str = Field("", max_length=64)
    feature_id: str = Field(..., max_length=64)
    task_id: str = Field(..., max_length=64)
    attempt: int = Field(..., ge=1, le=3)
    seat_label: str = Field("", max_length=32)
    backend: str = Field("", max_length=32)
    configured_model: str = Field("", max_length=200)
    resolved_model: str = Field("", max_length=200)
    duration_s: float = 0.0
    turns: int = 0
    terminal: str = Field("completed", max_length=16)
    error_class: str = Field("", max_length=120)
    declared_files: Optional[int] = None
    declared_files_known: bool = False
    provider_input_tokens: Optional[int] = None
    provider_output_tokens: Optional[int] = None
    ledger_input_tokens: Optional[int] = None
    ledger_output_tokens: Optional[int] = None
    ledger_settled_estimate_input_tokens: Optional[int] = None
    ledger_released_estimate_tokens: Optional[int] = None
    ledger_uncertain_tokens: Optional[int] = None
    ledger_overrun_tokens: Optional[int] = None
    ledger_counting_methods: List[str] = Field(default_factory=list)
    ledger_accounting_complete: Optional[bool] = None
    enforcement: str = Field("observe", max_length=16)
    turns_with_unknown_usage: int = 0
    calibration_eligible: bool = False
    turn_series: List[Tuple[int, Optional[int], Optional[int]]] = Field(default_factory=list)


class OutcomeRow(BaseModel):
    """The `outcome` JSONL line. Several per `attempt_uid` are expected."""

    kind: Literal["outcome"] = "outcome"
    ts: str
    attempt_uid: str = Field(..., min_length=8, max_length=64)
    job_id: str = Field("", max_length=64)
    feature_id: str = Field(..., max_length=64)
    task_id: str = Field(..., max_length=64)
    attempt: int = Field(..., ge=1, le=3)
    event_seq: int = Field(..., ge=1)
    outcome: str = Field(..., max_length=32)
    conflict_file_count: int = 0
    unexpected_file_count: int = 0
```
**Why this shape**: `turn_series` is `List[Tuple[int, Optional[int], Optional[int]]]` and NOT `List[List[int]]` — the latter rejects a turn the provider reported no usage for, which the transport explicitly produces (spec §10 R6). Every string field is bounded so a pathological value cannot blow the line budget, but the runtime check in the sink remains the authority (AC-22). `event_seq` exists because one attempt can legitimately emit `merge_conflict` then `merged` after a manual repair (`engine.py:407`).

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py` (CREATE — part 2: root + projection)
```python
def feature_file_name(feature_id: str) -> str:
    """Return `<feature_id>.jsonl`, or raise ValueError on an unsafe id.

    `feature_id` comes from a per-spec index header with no filename validator,
    so it is untrusted input to a path join (design research S6).
    """
    if not _SAFE_FEATURE_ID.match(feature_id or ""):
        raise ValueError(f"unsafe feature_id for a filename: {feature_id!r}")
    return f"{feature_id}.jsonl"


def resolve_durable_root(configured: Optional[str], *, worktree_base_path: str) -> Path:
    """Resolve and validate the telemetry root, or raise ValueError.

    An explicit absolute *configured* path wins. Otherwise the main checkout is
    derived from `git rev-parse --path-format=absolute --git-common-dir`, which
    points at the MAIN repository's `.git` even when called inside a linked
    worktree. A root that resolves under *worktree_base_path* is REFUSED: the
    dataset must outlive `git worktree remove`, and `conf.BASE_DIR` cannot be
    trusted to avoid it (spec §10 R7).
    """
    # FILL IN: (1) absolute `configured` -> use it; a relative one -> ValueError.
    # (2) otherwise run the git command, take the parent of the returned
    #     `.git` dir, and append "artifacts/logs/sdd-coder-usage".
    # (3) reject when the resolved path == worktree_base_path or is under it,
    #     mirroring the containment check at engine.py:193.
    # Bounded by AC-9; raise ValueError with the offending path in the message.
    raise NotImplementedError


def build_attempt_row(
    record: AttemptRecord, *, feature_id: str, job_id: str, declared_files: Optional[int]
) -> AttemptUsageRow:
    """Project an AttemptRecord onto a row by EXPLICIT ALLOWLIST.

    Never a `model_dump()`: `AttemptRecord.error` holds the full exception
    string (verified: engine.py:583) and a field added to that model later must
    not leak into the dataset by default (spec §10 R5, AC-7). Only
    `error_class` crosses over.

    Sets `calibration_eligible` = ledger accounting complete AND no turn
    reported unknown usage — the one place that rule lives.
    """
    # FILL IN: name every copied field; read ledger_* out of
    # `record.budget_report` with `.get(...)` so a missing report yields None
    # rather than KeyError; compute calibration_eligible. Bounded by AC-7
    # (no error/diagnostics text) and AC-21 (eligibility rule).
    raise NotImplementedError
```
**Why**: `resolve_durable_root` raises rather than falling back, because a silent fallback is exactly how the dataset would end up inside a disposable worktree. `build_attempt_row` is a hand-written projection so that adding a field to `AttemptRecord` is a no-op for privacy — the reviewer's R5 point generalised into a structural property.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py` (CREATE — part 3: sink)
```python
class CoderTelemetrySink:
    """One append-only JSONL file per feature under a validated root."""

    def __init__(self, root: str | Path, *, enabled: bool = True) -> None:
        self.logger = logging.getLogger(__name__)
        self._root = Path(root)
        self._enabled = enabled
        self._warned = False

    async def write_attempt(self, row: AttemptUsageRow) -> None:
        """Append one `attempt` row. Never raises."""
        await self._append(row.feature_id, row.model_dump_json())

    async def write_outcome(self, row: OutcomeRow) -> None:
        """Append one `outcome` row. Never raises."""
        await self._append(row.feature_id, row.model_dump_json())

    async def _append(self, feature_id: str, line: str) -> None:
        """Serialize-check then ONE os.write to an O_APPEND fd, off the loop.

        Runs the blocking write through `asyncio.to_thread`, the pattern
        `_journal` follows (verified: engine.py:472-488). Every failure is
        logged once at WARNING and dropped: a telemetry problem must never
        change a dispatch or a merge outcome (AC-11).
        """
        # FILL IN: no-op when disabled; encode the line + "\n"; drop with a
        # WARNING when len(payload) > MAX_LINE_BYTES (never truncate — that
        # would write invalid JSON); mkdir the root; then in a to_thread worker
        # open with os.O_WRONLY|os.O_CREAT|os.O_APPEND and do exactly one
        # os.write. Wrap everything in try/except Exception -> log once.
        # Bounded by AC-10 and AC-22.
        raise NotImplementedError
```
**Why**: `_append` is the single choke point for every row kind, so the size check, the directory creation and the swallow-and-log rule exist once. `self._warned` keeps a broken root from producing one WARNING per attempt across a long feature run.

### FILL IN checklist
- [ ] `telemetry.py::resolve_durable_root` — the three resolution/validation branches; bounded by AC-9
- [ ] `telemetry.py::build_attempt_row` — the explicit field allowlist + eligibility rule; bounded by AC-7, AC-21
- [ ] `telemetry.py::CoderTelemetrySink._append` — size check, mkdir, single `os.write`, swallow-and-log; bounded by AC-10, AC-11, AC-22
- [ ] `test_telemetry.py` — the seven test bodies below

---

## Acceptance Criteria

- [ ] `TurnUsage`-shaped tuples with `None` tokens round-trip through `AttemptUsageRow` (JSON in and out).
- [ ] A worst-case row — every string field at `max_length`, 101 turns — serializes to `<= MAX_LINE_BYTES`; the test asserts the actual number.
- [ ] `feature_file_name` accepts `"FEAT-554"` and raises `ValueError` for `"../etc"`, `"a/b"`, `""` and a 65-character id.
- [ ] `resolve_durable_root("/tmp/x", worktree_base_path="/tmp/x/wt")` returns `/tmp/x`; `resolve_durable_root("/tmp/x/wt/inside", worktree_base_path="/tmp/x/wt")` raises `ValueError`; a relative configured path raises `ValueError`.
- [ ] With `configured=None`, the root derives from `git rev-parse --path-format=absolute --git-common-dir` and lands in the main checkout even when the cwd is a linked worktree.
- [ ] `build_attempt_row` output contains no substring of the record's `error` field, and `calibration_eligible` is `False` when `turns_with_unknown_usage > 0` or accounting is incomplete.
- [ ] An unwritable root produces no exception and exactly one WARNING across ten writes.
- [ ] An oversized row is dropped with a WARNING; the file contains no partial line.
- [ ] Twenty concurrent `write_attempt` calls produce twenty lines, every one `json.loads`-able.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_telemetry.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_telemetry.py
import asyncio
import json

import pytest

from parrot.flows.dev_loop.sdd_coder.telemetry import (
    MAX_LINE_BYTES, AttemptUsageRow, CoderTelemetrySink, OutcomeRow,
    build_attempt_row, feature_file_name, resolve_durable_root,
)


def _row(**over) -> AttemptUsageRow:
    base = dict(ts="2026-09-12T00:00:00+00:00", attempt_uid="a" * 32,
                feature_id="FEAT-554", task_id="TASK-1", attempt=1)
    base.update(over)
    return AttemptUsageRow(**base)


class TestRowShape:
    def test_unknown_usage_round_trips(self):
        row = _row(turn_series=[(7, None, None)])
        assert json.loads(row.model_dump_json())["turn_series"] == [[7, None, None]]

    def test_worst_case_fits_the_budget(self):
        # FILL IN: every string field at max_length + 101 turns; assert
        # len(...encode()) <= MAX_LINE_BYTES and record the number
        raise NotImplementedError


class TestFeatureFileName:
    @pytest.mark.parametrize("bad", ["../etc", "a/b", "", "x" * 65])
    def test_rejects_unsafe(self, bad):
        with pytest.raises(ValueError):
            feature_file_name(bad)


class TestDurableRoot:
    def test_refuses_path_under_worktree_base(self, tmp_path):
        # FILL IN: bounded by AC-9 (spec §10 R7)
        raise NotImplementedError

    def test_derives_main_checkout(self, tmp_path):
        # FILL IN: git init a repo, add a linked worktree, resolve from inside
        # it, assert the root is under the MAIN checkout
        raise NotImplementedError


class TestProjection:
    def test_never_persists_exception_text(self):
        # FILL IN: an AttemptRecord whose error contains "SECRET-TOKEN-XYZ";
        # assert that substring is absent from the serialized row — bounded by AC-7
        raise NotImplementedError


class TestSink:
    async def test_concurrent_appends_stay_valid(self, tmp_path):
        # FILL IN: asyncio.gather 20 write_attempt calls; assert 20 parseable
        # lines — bounded by AC-10
        raise NotImplementedError

    async def test_failures_never_raise(self, tmp_path):
        # FILL IN: point the sink at an unwritable root; assert no exception
        # over ten writes and exactly one WARNING — bounded by AC-11
        raise NotImplementedError
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** — §2 Data Models, §3 Module 4, §10 R5/R6/R7 and the closing size note.
2. **Check dependencies** — none, but note that `AttemptRecord`'s new fields arrive in TASK-3192; read `record.budget_report` etc. defensively with `getattr`/`.get`.
3. **Verify the Codebase Contract** — confirm `sdd_coder/telemetry.py` does not exist and re-read `engine.py:472-488`.
4. **Update status** in `sdd/tasks/index/sdd-coder-bedrock-token-telemetry.json` → `"in-progress"`.
5. **Implement** from the blueprint; keep the allowlist explicit and add no locking.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-3191-coder-telemetry-sink.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-coder (gemini seat) via parrot-sdd-coder orchestrator; test-fixture bugs repaired and merge verified by sdd-worker
**Date**: 2026-09-12
**Notes**: Implemented `AttemptUsageRow`/`OutcomeRow`, `feature_file_name`,
`resolve_durable_root` (with worktree-containment refusal) and
`build_attempt_row` (explicit allowlist projection, never `model_dump()`)
in `parrot/flows/dev_loop/sdd_coder/telemetry.py`, plus `CoderTelemetrySink`
(append-only, `O_APPEND`, `MAX_LINE_BYTES` enforced at write time, never
raises). During verification, 3 of the coder's own tests in
`test_telemetry.py` failed because they set `record.task_id` /
`record.enforcement` on `AttemptRecord`, which has neither field (per the
spec's own `build_attempt_row(record, *, feature_id, job_id,
declared_files)` signature, `task_id` is not sourced from the record), and
because a concurrent-write fixture used a 6-character `attempt_uid` below
`AttemptUsageRow`'s 8-character minimum. sdd-worker fixed the test fixture
only (removed the two invalid attribute sets, lengthened the fixture uid);
production `telemetry.py` was not touched. All 14 tests now pass; `ruff
check` clean.

**Deviations from spec**: none (test-only fixup, see note above)

**Post-merge adversarial review addendum**: a full-feature code review after
all 11 tasks landed found `build_attempt_row` read `budget_report.get(
"ledger_input_tokens")` etc., but `BudgetReport.model_dump()`'s real fields
are UNPREFIXED — no `"ledger_"`-prefixed key exists anywhere in that model.
Every `ledger_*` field on every row, and `calibration_eligible`, were always
`None`/`False` for every attempt ever recorded. `task_id` was also read via
`getattr(record, "task_id", "")` from a field `AttemptRecord` doesn't have,
so it was always `""`. Both fixed in `build_attempt_row` (unprefixed field
mapping; `task_id` promoted to a required parameter) with regression
assertions added to this task's own test. See FEAT-554's final commit for
full detail.

Seat: gemini · Backend: google-compat · Model: gemini-3.5-flash · Attempts: 1 · Duration: 141.6s · Tokens: 1408386/8374
