# TASK-5716: Observe SQLite and ledger phases without changing persistence

**Feature**: FEAT-902 - Wiki and ledger SQLite hardening
**Spec**: `sdd/specs/wiki-ledger-sqlite-hardening.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5715
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Depends on TASK-5715 for _append_durably and shared ledger/index.py serialization; TASK-5714's probe and ledger/log.py edits are transitively available. Adds timings to store.py and service.py without changing resource lifetime.

## Context

Implement spec M4 and AC7/AC8. Distinguish connection/setup, writer wait, transaction, commit, replay and durable-log cost before proposing connection reuse.

## Scope

- Add structured DEBUG phase records and structured stale-read fallback to existing loggers.
- Observe connection_open/setup, begin_wait, transaction_body, commit/rollback, log_append/fsync, replay and sync_probe.
- Label success/error/cancel correctly; guard debug work and isolate logger failures from DB outcomes.
- Test phase records, unchanged exception behavior, FTS results and read-only behavior.

**NOT in scope**: No metrics DB, global registry, new configuration/dependency, SQL/payload logs, durability tuning or persistent connections.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` | MODIFY | Scoped implementation |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py` | MODIFY | Scoped implementation |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py` | MODIFY | Scoped implementation |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py` | MODIFY | Scoped implementation |
| `packages/ai-parrot/tests/knowledge/wiki/test_sqlite_timing.py` | CREATE | Focused validation |

## Codebase Contract (Anti-Hallucination)

Verified against base `0eb46c010bf33b05fabc924253ced5a3d21b02fb` on 2026-11-16. Existing signatures and exact edit anchors were re-read; dependency-produced symbols are explicitly distinguished from existing ones. Recheck them after predecessor commits. If a required import or interface differs, stop and report drift instead of guessing.

### Verified Imports

```python
import logging
import os
import time
from pathlib import Path
from typing import AsyncIterator
import aiosqlite
import pytest
from parrot.knowledge.wiki.store import SQLiteWikiStore, SQLitePragmaPolicy, WikiPageRecord, WikiStoreBusy
from parrot.knowledge.wiki.ledger.log import LedgerLog
from parrot.knowledge.wiki.ledger.index import LedgerIndex
from parrot.knowledge.wiki.ledger.service import LedgerService
from parrot.knowledge.wiki.ledger.events import LedgerEvent
```

Stdlib imports and installed pytest/aiosqlite/Pydantic were verified in the activated repository environment; no new dependency is authorized. Imports of new symbols belong to their named producer below and must be verified after it lands.

### Existing Signatures and Dependency Interfaces

- packages/ai-parrot/src/parrot/knowledge/wiki/store.py:1481: _open(*,writable: bool) -> AsyncIterator[aiosqlite.Connection]; :1853 _write(operation: str) owns all transaction boundaries.
- packages/ai-parrot/src/parrot/knowledge/wiki/store.py:279,300,606: SQLitePragmaPolicy, WikiStoreBusy (BEGIN-boundary only) and WikiPageRecord.
- packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py:21,83: append(event) -> tuple[str,int], append_line(line: str) -> int; both fsync before return.
- packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py:306,323: sync and _sync_locked preserve event counts; new probe and durable helper arrive through dependencies.
- packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py:220: _sync_best_effort catches only WikiStoreBusy and currently emits a warning.
- Existing store uses self.logger; ledger modules already expose module logger objects. Preserve those logging conventions.
- packages/ai-parrot/src/parrot/knowledge/wiki/store.py:1369: db_path property returns pathlib.Path, so db_name uses db_path.name.

### Does NOT Exist

- No timing sink/metrics storage exists or is added; reuse Python logging.
- Candidate-only timings do not exist on the benchmark baseline.
- persistent_writer is not implemented and must remain unchanged.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/store.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_sqlite_timing.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore._open",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore._write",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLitePragmaPolicy",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#WikiStoreBusy",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#WikiPageRecord",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py#LedgerLog",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py#LedgerLog.append",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py#LedgerLog.append_line",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py#LedgerIndex",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py#LedgerIndex.sync",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py#LedgerIndex._sync_locked",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService._sync_best_effort",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py#LedgerEvent",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore.db_path"
  ]
}
```

## Implementation Notes

Keep the existing SQLite + aiosqlite stack, separate wiki/ledger databases and connection-per-operation lifecycle. Preserve asynchronous I/O and existing transaction ownership; offload blocking file work. No new dependency, schema migration or persistent connection is authorized. Tests use disposable state only.

Blueprint gaps below are bounded authoring instructions, not deliverable code. Complete all marked branches and assertions; never ship stubs. A CREATE block is a whole-file starting point and a MODIFY block attaches only to the quoted owner; preserve surrounding and predecessor changes.

## Implementation Blueprint

### Steps (in order)

1. Measure with time.perf_counter without altering transaction control — duration instrumentation must not become persistence logic.
2. Emit existing-logger structured records only at DEBUG — no new database work or SQL/event payload leakage.
3. Instrument append_line as well as append — imported shared-log events also incur fsync.
4. Exercise success/error/cancel and a throwing logging handler — telemetry cannot change committed data or error propagation.

### `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` (MODIFY)

Verified attachment anchor at `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:1853`; exact occurrence count **1** on authoring base `0eb46c010bf33b05fabc924253ced5a3d21b02fb` (recheck after dependencies land):

```text
    async def _write(self, operation: str) -> AsyncIterator[aiosqlite.Connection]:
```

```python
# Use existing imports when present; add time/os only if absent.
# Preserve _open/_write signatures and all current error/rollback behavior.
# FILL IN: instrument _open connection acquisition then connection setup separately.
# FILL IN: instrument _write BEGIN wait, yielded body, COMMIT and ROLLBACK.
# Record through self.logger with event="wiki.sqlite.timing" and extra fields:
# operation, phase, duration_ms, outcome, pid, db_name (basename only).
# Outcome values: "success", "error", "cancelled"; classify from actual completion.
# Use perf_counter and isEnabledFor(logging.DEBUG); log-handler failures are contained.
# No SQL strings, full paths, actors, issue bodies, payloads or metric writes.
# Do not label a failed/cancelled COMMIT as success; preserve WikiStoreBusy mapping.
```

Only timing is added to the shared store. Existing rollback/connection cleanup remains the authoritative behavior.

### `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py` (MODIFY)

Verified attachment anchor at `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py:111`; exact occurrence count **1** on authoring base `0eb46c010bf33b05fabc924253ced5a3d21b02fb` (recheck after dependencies land):

```text
    def iter_events(self, from_offset: int = 0) -> Iterator[tuple[LedgerEvent, int]]:
```

```python
# The verified anchor identifies LedgerLog; retain TASK-5714's probe.
# FILL IN: observe existing append AND append_line blocks with module logger.
# Phases log_append and log_fsync; fsync is inclusive within append, not additive.
# operation: "ledger.append" / "ledger.append_line"; db_name: "ledger.db".
# Emit only metadata and duration; preserve original write count, fsync and exceptions.
# FILL IN: never let a logging handler failure turn durable success into failure.
```

Measure fsync instead of assuming the SQLite connection dominates end-to-end write cost.

### `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py` (MODIFY)

Verified attachment anchor at `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py:306`; exact occurrence count **1** on authoring base `0eb46c010bf33b05fabc924253ced5a3d21b02fb` (recheck after dependencies land):

```text
    async def sync(self, conn: "aiosqlite.Connection | None" = None) -> int:
```

```python
# Keep predecessor helpers and signatures. Use the existing module logger.
# FILL IN: time probe evaluation with phase="sync_probe" and fast_path bool.
# FILL IN: time locked replay with phase="replay" and applied_events count.
# On failure/cancel record the actual outcome; do not invent applied counts.
# Use db_name=self.store.db_path.name; never include event payloads.
# Avoid duplicate counting of nested replay during claim; document inclusive phases.
```

Replay and no-op avoidance are separate sources of latency improvement and must be attributable.

### `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py` (MODIFY)

Verified attachment anchor at `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py:220`; exact occurrence count **1** on authoring base `0eb46c010bf33b05fabc924253ced5a3d21b02fb` (recheck after dependencies land):

```text
    async def _sync_best_effort(self) -> None:
```

```python
# Preserve the catch scope and warning semantics inside _sync_best_effort.
# FILL IN: add structured warning fields event="wiki.ledger.stale_read",
# operation="ledger.sync", outcome="busy", pid and basename db_name.
# Do not swallow errors other than WikiStoreBusy or change public responses.
# Contain handler failures without concealing the original storage outcome.
```

Best-effort reads must remain observable as stale without changing the existing tool response contract.

### `packages/ai-parrot/tests/knowledge/wiki/test_sqlite_timing.py` (CREATE)

```python
"""FEAT-902 timing records preserve SQLite and ledger semantics."""
import logging
from pathlib import Path
import pytest
from parrot.knowledge.wiki.store import SQLiteWikiStore, SQLitePragmaPolicy, WikiPageRecord, WikiStoreBusy
from parrot.knowledge.wiki.ledger.service import LedgerService
from parrot.knowledge.wiki.ledger.log import LedgerLog
from parrot.knowledge.wiki.ledger.events import LedgerEvent

@pytest.mark.asyncio
async def test_phase_records_and_counts(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Connection, transaction, probe, replay and fsync observations are attributable."""
    # FILL IN: real temporary operations; inspect extra fields, counts and durations.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_telemetry_failure_does_not_change_storage(tmp_path: Path) -> None:
    """A throwing logging handler cannot change a commit/error/cancel outcome."""
    # FILL IN: success, busy, body error and cancellation; verify persisted results.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_payload_free_timings_and_readonly_fts(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Timing output excludes sensitive fields and preserves wiki FTS/read-only behavior."""
    # FILL IN: sentinel payload/full-path values, DEBUG off, append_line and FTS reads.
    raise NotImplementedError
```

The meaningful invariant is unchanged persistence behavior under instrumentation, not a test mirroring clock arithmetic.

### FILL IN Checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` — complete its marked implementation/prose and boundary cases using Scope, Acceptance Criteria and Test Specification.
- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py` — complete its marked implementation/prose and boundary cases using Scope, Acceptance Criteria and Test Specification.
- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py` — complete its marked implementation/prose and boundary cases using Scope, Acceptance Criteria and Test Specification.
- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py` — complete its marked implementation/prose and boundary cases using Scope, Acceptance Criteria and Test Specification.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/test_sqlite_timing.py` — complete its marked implementation/prose and boundary cases using Scope, Acceptance Criteria and Test Specification.
- [ ] Verify imports, types, exact attachment anchors and dependency outputs in the implementation checkout.
- [ ] Remove every unfinished scaffold from delivered files; inspect the scoped diff and run all mandatory gates.

## Acceptance Criteria

- [ ] AC1: All required phases use monotonic duration and structured operation/phase/outcome/pid/db_name fields.
- [ ] AC2: Applied event/fast-path counts and stale-read warnings are attributable; inclusive phases are documented.
- [ ] AC3: Timing records expose no SQL, payload, actor or full path and perform no persistence or provider calls.
- [ ] AC4: Logging failures and DEBUG-off mode preserve data, exception and cancellation behavior.
- [ ] AC5: Both append routes retain fsync; FTS/read-only and BEGIN-boundary error contracts remain intact.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_sqlite_timing.py -q`

## Test Specification

Use caplog and controlled logging-handler failures with real temporary SQLite/log files. Assert classification for success, BUSY, rollback and cancellation, and validate FTS search/read-only results. Avoid performance thresholds in unit tests.

Run the task-specific commands above. The feature-wide regression contract is cached in the per-spec index and runs at its configured SDD gates; do not replace these focused checks with bare pytest or a directory scan.

## Agent Instructions

1. Start with `$sdd-start TASK-5716`; the implementation workflow provisions the feature worktree. Do not implement on dev.
2. Verify predecessors are done in `sdd/tasks/index/wiki-ledger-sqlite-hardening.json` and recheck this task's contracts.
3. Implement only the declared files, preserve other agents' changes, and complete every acceptance gate. Store execution logs under `artifacts/logs/`.
4. Use `parrot sdd task finalize` with real TaskCompletionEvidence and the exact implementation HEAD. The finalizer owns the completion note and active-to-completed move; do not hand-edit them.

## Completion Note

- Task: TASK-5716
- Feature: wiki-ledger-sqlite-hardening
- Implementation SHA: b998e0f9b55efbdb113846c26de1d36dcbb5f41a
- Closed at (UTC): 2026-11-16T22:26:47+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 651s · Tokens: n/a |
