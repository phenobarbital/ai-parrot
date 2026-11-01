# TASK-4990: SpecUsageRecorder — durable per-feature usage sink

**Feature**: FEAT-783 — Unified usage & cost metrics per SDD spec
**Spec**: `sdd/specs/unified-usage.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4985
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5, G5, AC-10, design review S4. The only per-run store, `RunLedgerRecorder`, is
in-memory with a no-op `aclose()`, so no separate process can read it. This task adds a durable
`AbstractLogger` **sink** (not an `EventProvider`) that appends one JSONL row per attributed
`UsageRecord`, under a root resolved with FEAT-554's rule (main checkout, refused inside the
worktree base).

---

## Scope

- Create `recorders/spec_usage.py` with `SpecUsageRecorder(AbstractLogger)`.
- Root: an explicit absolute `root` wins. Otherwise use `resolve_durable_root(None, worktree_base_path=...).parent / "sdd-spec-usage"`, which lands beside `sdd-coder-usage/` in the main checkout. Re-check that the final root is not inside the worktree base; raise `ValueError` when it is.
- `record()`: skip records with no `feat_id`. Otherwise append `record.model_dump_json()` to `<root>/<feat_id>.jsonl` with one `os.write` on an `O_APPEND` fd, off the loop. Fail-open: it never raises and warns once.
- `aclose()`: await pending writes. It is not a no-op.
- Add a `read_spec_usage(root, feat_id) -> list[UsageRecord]` helper for readers (TASK-4994). It skips malformed lines.
- Factory/config: add `"spec_usage"` to `UsageBackend`, plus a `spec_usage_root: Optional[str]` config field (explicit absolute path). Add a factory branch that builds the recorder with `worktree_base_path` from `parrot.conf` (FILL IN).
- Tests, including a **subprocess** reader (AC-10).

**NOT in scope**: registering the sink for sdd-coder executions (TASK-4992); the report (TASK-4994).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/observability/recorders/spec_usage.py` | CREATE | Sink + reader helper |
| `packages/ai-parrot/src/parrot/observability/recorders/factory.py` | MODIFY | `spec_usage` branch |
| `packages/ai-parrot/src/parrot/observability/config.py` | MODIFY | Literal value + `spec_usage_root` |
| `packages/ai-parrot/tests/unit/observability/test_spec_usage_recorder.py` | CREATE | Tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.observability.recorders.base import AbstractLogger              # base.py:16
from parrot.observability.recorders.models import UsageRecord               # models.py:22
from parrot.flows.dev_loop.sdd_coder.telemetry import resolve_durable_root, feature_file_name  # telemetry.py:107, :~95
```

### Existing Signatures to Use
```python
# recorders/base.py
class AbstractLogger:                     # :16 — name attr; async record(self, record: UsageRecord) -> None (:30); async aclose(self) -> None (:46, default no-op)
# sdd_coder/telemetry.py
def resolve_durable_root(configured: Optional[str], *, worktree_base_path: str) -> Path   # :107 — default ends in artifacts/logs/sdd-coder-usage; raises ValueError
def feature_file_name(feature_id: str) -> str   # returns "<id>.jsonl"; raises ValueError on unsafe id (path-join guard)
class CoderTelemetrySink: _append(...)  # :280-330 — the O_APPEND + asyncio.to_thread + warn-once pattern to mirror
# recorders/factory.py
def build_recorders_from_config(config) -> list[AbstractLogger]   # :22; branch anchor `    if backend == "logging":` (:41)
# config.py
UsageBackend = Literal["none", "logging", "prometheus", "otel", "traceloop"]   # :17
    pricing_override_path: Optional[str] = None   # :215
```

### Does NOT Exist
- ~~`parrot.observability.recorders.SpecUsageRecorder`~~ — this task creates it (module `recorders.spec_usage`)
- ~~a `register()` on the sink~~ — it is a SINK; never subscribe it directly
- ~~any write under `knowledge/wiki/ledger/`~~ — forbidden (AC-14)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/observability/recorders/spec_usage.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/observability/recorders/factory.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/observability/config.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/observability/test_spec_usage_recorder.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/observability/recorders/base.py#AbstractLogger",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py#resolve_durable_root",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py#feature_file_name",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py#CoderTelemetrySink",
    "sym:packages/ai-parrot/src/parrot/observability/recorders/factory.py#build_recorders_from_config"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Import `telemetry.py` **lazily** inside `__init__`, because `observability` must not import `flows.dev_loop` at module import time (import-weight and cycle risk).
- One line ≤ 64 KiB. Reuse `MAX_LINE_BYTES` from telemetry.py if it is exported; otherwise define a local constant.
- `cumulative_cost_usd` is process-cumulative. It may be written, but readers must never sum it (spec §7 gotcha). Say so in the module docstring.

---

## Implementation Blueprint

### Steps (in order)
1. Write the recorder by mirroring `CoderTelemetrySink._append`, because the posture (fail-open, warn once, O_APPEND) is the spec's mandated pattern.
2. Track in-flight writes in a set of tasks, so `aclose()` can await them.
3. Add the reader helper.
4. Add the config field + Literal value, then the factory branch.
5. Tests: refused root, write/read round-trip, write failure does not raise, a subprocess reads rows after the writer exits.

### `packages/ai-parrot/src/parrot/observability/recorders/spec_usage.py` (CREATE)
```python
"""SpecUsageRecorder — durable per-feature usage sink (FEAT-783 M5).

A SINK, not an EventProvider: the existing UsageRecordingSubscriber owns the subscription
(run_ledger.py:1-14 pattern). Root resolution reuses FEAT-554's rule (main checkout via
git-common-dir; refused inside the worktree base) so rows outlive `git worktree remove`.
`cumulative_cost_usd` is process-cumulative: readers must never sum it.
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

from parrot.observability.recorders.base import AbstractLogger
from parrot.observability.recorders.models import UsageRecord

logger = logging.getLogger(__name__)

_MAX_LINE_BYTES = 64 * 1024


class SpecUsageRecorder(AbstractLogger):
    """Append one JSONL row per attributed UsageRecord to ``<root>/<feat_id>.jsonl``."""

    name: str = "spec_usage"

    def __init__(self, root: Optional[Path] = None, *, worktree_base_path: str) -> None:
        from parrot.flows.dev_loop.sdd_coder.telemetry import resolve_durable_root  # noqa: PLC0415

        if root is not None:
            resolved = resolve_durable_root(str(root), worktree_base_path=worktree_base_path)
        else:
            resolved = resolve_durable_root(None, worktree_base_path=worktree_base_path).parent / "sdd-spec-usage"
            # FILL IN: re-run the "not inside worktree base" check on `resolved` (raise ValueError) — bounded by AC-10
        self._root = resolved
        self._pending: set[asyncio.Task[None]] = set()
        self._warned = False

    @property
    def root(self) -> Path:
        """The validated durable root."""
        return self._root

    async def record(self, record: UsageRecord) -> None:
        """Append one row keyed by feat_id. Fail-open: never raises, warns once."""
        if not record.feat_id:
            return
        # FILL IN: feature_file_name(record.feat_id) (lazy import), encode model_dump_json()+"\n", size bound,
        # asyncio.to_thread(os.open O_WRONLY|O_CREAT|O_APPEND 0o644 + single os.write), track the task in
        # self._pending, warn once on any exception — bounded by telemetry.py:280-330 posture
        raise NotImplementedError

    async def aclose(self) -> None:
        """Await in-flight writes. Unlike RunLedgerRecorder.aclose this is NOT a no-op (S4)."""
        if self._pending:
            await asyncio.gather(*self._pending, return_exceptions=True)


def read_spec_usage(root: Path, feat_id: str) -> list[UsageRecord]:
    """Read every row for *feat_id*; malformed lines are skipped (never raises on content)."""
    # FILL IN: feature_file_name guard, missing file -> [], UsageRecord.model_validate_json per line in try/except
    raise NotImplementedError
```

### `factory.py` + `config.py` (MODIFY)
```python
# config.py — occurrences: 1 (verified: grep -c 'UsageBackend = Literal\["none", "logging", "prometheus", "otel", "traceloop"\]' config.py), :17
UsageBackend = Literal["none", "logging", "prometheus", "otel", "traceloop", "spec_usage"]
# config.py — AFTER `    pricing_override_path: Optional[str] = None` (:215, 1 occurrence)
    spec_usage_root: Optional[str] = None  # FEAT-783: absolute durable root for SpecUsageRecorder
```
```python
# factory.py — occurrences: 1 (verified: grep -c '    if backend == "logging":' factory.py), :41
# Add an `elif backend == "spec_usage":` branch before the final `else:`
    elif backend == "spec_usage":
        from parrot.observability.recorders.spec_usage import SpecUsageRecorder  # noqa: PLC0415

        # FILL IN: worktree_base_path from parrot.conf (grep the sdd-coder engine for the setting it passes to
        # resolve_durable_root and reuse it verbatim); Path(config.spec_usage_root) when set; on ValueError log
        # a warning and add no recorder — bounded by AC-10 (never inside a worktree)
```
Also document the new value in the `usage_backend` docstring (config.py:101).

### `test_spec_usage_recorder.py` (CREATE)
```python
"""FEAT-783 TASK-4990 — durable sink (AC-10)."""
import subprocess
import sys

import pytest


def test_root_inside_worktree_base_is_refused(tmp_path) -> None:
    # FILL IN
    ...


@pytest.mark.asyncio
async def test_round_trip_and_unattributed_skipped(tmp_path) -> None:
    # FILL IN: record 2 attributed + 1 without feat_id, aclose(), read_spec_usage returns 2
    ...


@pytest.mark.asyncio
async def test_write_failure_never_raises(tmp_path) -> None:
    # FILL IN: root is a file (not a dir) -> record() returns, one warning logged
    ...


@pytest.mark.asyncio
async def test_rows_readable_by_separate_process(tmp_path) -> None:
    # FILL IN: write + aclose, then subprocess.run([sys.executable, "-c", "<read_spec_usage ... print(len)>"]) -> AC-10
    ...
```

### FILL IN checklist
- [ ] Root re-check; bounded by AC-10
- [ ] `record()` body; bounded by the telemetry.py posture
- [ ] `read_spec_usage`
- [ ] Factory `worktree_base_path` source
- [ ] Test bodies

---

## Acceptance Criteria

- [ ] AC-10: rows survive process exit, live outside any worktree, and a separate process can read them.
- [ ] A write failure never raises; it warns once.
- [ ] `aclose()` flushes pending writes.

## Validation Commands
- `pytest packages/ai-parrot/tests/unit/observability/test_spec_usage_recorder.py -q`
- `pytest packages/ai-parrot/tests/unit/observability/test_config.py -q`

## Test Specification
See blueprint.

## Agent Instructions
Four files only. `PYTHONPATH=packages/ai-parrot/src`.

## Completion Note

- Task: TASK-4990
- Feature: unified-usage
- Implementation SHA: 2cb7c67a72e457144c1f516879703c46fe3d10c2
- Closed at (UTC): 2026-10-31T00:39:50+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-sol · Backend: codex · Model: gpt-5.6-sol · Attempts: 1 · Duration: 125.5s · Tokens: n/a |
