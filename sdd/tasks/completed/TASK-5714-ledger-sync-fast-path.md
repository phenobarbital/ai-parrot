# TASK-5714: Bounded log probe and no-op ledger synchronization

**Feature**: FEAT-902 - Wiki and ledger SQLite hardening
**Spec**: `sdd/specs/wiki-ledger-sqlite-hardening.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5713
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Depends on TASK-5713 for LedgerCursorInvalid/read_cursor_in and serializes the shared ledger/index.py writer. Modifies ledger/log.py and creates its own fast-path test file.

## Context

Implement spec M2 and AC3/AC4/AC5. Read-facing sync should not compete for the SQLite writer when a conservative bounded observation proves there are no new events.

## Scope

- Add LedgerLog.probe_cursor(offset, last_event_id) with current/replay/uncertain results.
- Add C1 -> off-thread bounded probe -> C2 preflight only to standalone sync(conn=None).
- Return 0 only for current with unchanged cursors; otherwise revalidate and replay under BEGIN IMMEDIATE.
- Cover actual get/list/ready calls under a peer writer, replacement/truncation and append races.

**NOT in scope**: No shortcut inside sync(conn), claim, close or unclaim; no mtime/size-only cache; no replay batching, parsing-policy change or new log format.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py` | MODIFY | Scoped implementation |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py` | MODIFY | Scoped implementation |
| `packages/ai-parrot/tests/knowledge/wiki/test_ledger_sync_fast_path.py` | CREATE | Focused validation |

## Codebase Contract (Anti-Hallucination)

Verified against base `0eb46c010bf33b05fabc924253ced5a3d21b02fb` on 2026-11-16. Existing signatures and exact edit anchors were re-read; dependency-produced symbols are explicitly distinguished from existing ones. Recheck them after predecessor commits. If a required import or interface differs, stop and report drift instead of guessing.

### Verified Imports

```python
import asyncio
import os
import json
from typing import Literal
from pathlib import Path
import multiprocessing
import pytest
from parrot.knowledge.wiki.ledger.log import LedgerLog
from parrot.knowledge.wiki.ledger.index import LedgerIndex
from parrot.knowledge.wiki.ledger.store import LedgerStore
from parrot.knowledge.wiki.ledger.service import LedgerService
from parrot.knowledge.wiki.ledger.events import LedgerEvent
from parrot.knowledge.wiki.store import SQLitePragmaPolicy, WikiStoreBusy
```

Stdlib imports and installed pytest/aiosqlite/Pydantic were verified in the activated repository environment; no new dependency is authorized. Imports of new symbols belong to their named producer below and must be verified after it lands.

### Existing Signatures and Dependency Interfaces

- packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py:10,111: LedgerLog.path is the log filename; iter_events(from_offset: int = 0) yields (LedgerEvent, line-start offset).
- packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py:306,323: sync(conn=None) -> int; _sync_locked(conn) -> tuple[int,int,str | None].
- packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py:75: read_cursor() -> tuple[int,str | None]; TASK-5713 supplies LedgerCursorInvalid and coherent reads.
- packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py:195,276,300,336: from_dir(ledger_dir: Path, *, sqlite_policy=None), ready_work(), list_issues(), get_issue(issue_id).
- packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py:103: LedgerEvent validates the anchor; event_id is the cursor identity.
- packages/ai-parrot/src/parrot/knowledge/wiki/store.py:279,300: SQLitePragmaPolicy and WikiStoreBusy remain the bounded writer policy.
- Planned dependency import: from parrot.knowledge.wiki.ledger.store import LedgerCursorInvalid (created by TASK-5713; reverify after it lands).

### Does NOT Exist

- LedgerLog.probe_cursor is introduced here; there is no log-generation cache to reuse.
- read_cursor_in/LedgerCursorInvalid are dependency outputs, not present on the original base.
- File size alone cannot prove a log's identity or cursor validity.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_ledger_sync_fast_path.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py#LedgerLog",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py#LedgerLog.iter_events",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py#LedgerIndex",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py#LedgerIndex.sync",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py#LedgerIndex._sync_locked",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py#LedgerStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py#LedgerStore.read_cursor",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService.from_dir",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService.ready_work",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService.list_issues",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService.get_issue",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py#LedgerEvent",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLitePragmaPolicy",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#WikiStoreBusy"
  ]
}
```

## Implementation Notes

Keep the existing SQLite + aiosqlite stack, separate wiki/ledger databases and connection-per-operation lifecycle. Preserve asynchronous I/O and existing transaction ownership; offload blocking file work. No new dependency, schema migration or persistent connection is authorized. Tests use disposable state only.

Blueprint gaps below are bounded authoring instructions, not deliverable code. Complete all marked branches and assertions; never ship stubs. A CREATE block is a whole-file starting point and a MODIFY block attaches only to the quoted owner; preserve surrounding and predecessor changes.

## Implementation Blueprint

### Steps (in order)

1. Implement the binary bounded probe — validating the anchor plus EOF avoids scanning the tail during every read.
2. Insert the preflight in conn=None only — mutations still need serialized replay/ownership checks.
3. Re-read the cursor after probing and again inside a fallback writer — never replay a tail captured before acquiring the lock.
4. Prove service reads bypass a held peer writer when caught up — helper-only tests would miss the original contention path.

### `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py` (MODIFY)

Verified attachment anchor at `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py:111`; exact occurrence count **1** on authoring base `0eb46c010bf33b05fabc924253ced5a3d21b02fb` (recheck after dependencies land):

```text
    def iter_events(self, from_offset: int = 0) -> Iterator[tuple[LedgerEvent, int]]:
```

```python
# Extend typing imports with Literal. Insert before iter_events inside LedgerLog.
def probe_cursor(self, offset: int, last_event_id: str | None) -> Literal["current", "replay", "uncertain"]:
    """Validate the exact cursor anchor and EOF with bounded read-only I/O."""
    # FILL IN: one binary descriptor; before/after fstat + pathname identity (AC1).
    # Read at most 4097 anchor bytes and one suffix byte; require complete newline.
    # Stable matching anchor+EOF -> current; any suffix -> replay.
    # Changed metadata, replacement, missing populated log, invalid anchor -> uncertain.
    # Empty cursor is current only with stable empty/absent log.
    # FileNotFound races -> uncertain; other I/O/permission errors propagate.
    raise NotImplementedError
# Do not change iter_events parsing or append semantics.
```

The probe is only a conservative observation and must not convert uncertainty into a lock-free success.

### `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py` (MODIFY)

Verified attachment anchor at `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py:306`; exact occurrence count **1** on authoring base `0eb46c010bf33b05fabc924253ced5a3d21b02fb` (recheck after dependencies land):

```text
    async def sync(self, conn: "aiosqlite.Connection | None" = None) -> int:
```

```python
# Keep TASK-5713's runtime LedgerCursorInvalid import.
async def sync(self, conn: "aiosqlite.Connection | None" = None) -> int:
    """Skip writer acquisition only for a validated standalone no-op."""
    if conn is not None:
        applied, _offset, _event_id = await self._sync_locked(conn)
        return applied
    # FILL IN: C1, to_thread(probe_cursor), C2; catch ONLY LedgerCursorInvalid.
    # Return 0 ONLY when result == "current" and C1 == C2 (AC2/AC3).
    async with self.store.ledger_transaction("ledger.sync") as new_conn:
        applied, _offset, _event_id = await self._sync_locked(new_conn)
        return applied
```

The fallback keeps the existing lock boundary and rereads transactional state rather than trusting a pre-lock snapshot.

### `packages/ai-parrot/tests/knowledge/wiki/test_ledger_sync_fast_path.py` (CREATE)

```python
"""FEAT-902 no-op sync, probe races and service-level concurrency."""
from pathlib import Path
import asyncio
import multiprocessing
import os
import pytest
from parrot.knowledge.wiki.ledger.log import LedgerLog
from parrot.knowledge.wiki.ledger.events import LedgerEvent
from parrot.knowledge.wiki.ledger.service import LedgerService
from parrot.knowledge.wiki.store import SQLitePragmaPolicy, WikiStoreBusy

@pytest.fixture
def service(tmp_path: Path) -> LedgerService:
    """Use a disposable service, never the repository's real ledger."""
    return LedgerService.from_dir(tmp_path / "ledger", sqlite_policy=SQLitePragmaPolicy(busy_timeout_s=1))

@pytest.mark.asyncio
async def test_caught_up_reads_do_not_take_writer(service: LedgerService) -> None:
    """get/list/ready complete while a spawned peer holds BEGIN IMMEDIATE."""
    # FILL IN: initialize, trace SQL, synchronize peer and assert no own BEGIN (AC4).
    raise NotImplementedError

def test_probe_cursor_race_matrix(tmp_path: Path) -> None:
    """Replacement, truncation, malformed anchors and suffixes fail conservatively."""
    # FILL IN: parameterize spec §2 cases; assert bounded reads (AC1).
    raise NotImplementedError

@pytest.mark.asyncio
async def test_pending_replay_revalidates_under_lock(service: LedgerService) -> None:
    """C1/C2 changes and append races use transactional replay without skips."""
    # FILL IN: controlled interleavings, real events and unchanged mutation exclusion.
    raise NotImplementedError
```

Exercise public reads and actual process contention; monkeypatched return values alone cannot demonstrate the intended improvement.

### FILL IN Checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py` — complete its marked implementation/prose and boundary cases using Scope, Acceptance Criteria and Test Specification.
- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py` — complete its marked implementation/prose and boundary cases using Scope, Acceptance Criteria and Test Specification.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/test_ledger_sync_fast_path.py` — complete its marked implementation/prose and boundary cases using Scope, Acceptance Criteria and Test Specification.
- [ ] Verify imports, types, exact attachment anchors and dependency outputs in the implementation checkout.
- [ ] Remove every unfinished scaffold from delivered files; inspect the scoped diff and run all mandatory gates.

## Acceptance Criteria

- [ ] AC1: Probe reads bounded anchor/suffix bytes; stable identity and exact event-id anchor are required for current.
- [ ] AC2: Only standalone sync can return early; C1/C2 must match; invalid cursor selects locked recovery.
- [ ] AC3: Missing/populated, replacement, truncation and malformed/partial cases cannot skip replay; real I/O errors propagate.
- [ ] AC4: Initialized get/list/ready emits no BEGIN IMMEDIATE while caught up, even with a peer writer.
- [ ] AC5: Pending work preserves busy behavior; claim/close/unclaim remain serialized and accepted events are not skipped.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_ledger_sync_fast_path.py -q`

## Test Specification

Use spawn/Event/Barrier, not sleeps. Include same-size replacement, stable absent/empty log, EOF, suffix, invalid event id, C1/C2 changes, log append immediately before/after probe and schema initialization exemption. Verify no schema/FTS regressions via the cached feature contract.

Run the task-specific commands above. The feature-wide regression contract is cached in the per-spec index and runs at its configured SDD gates; do not replace these focused checks with bare pytest or a directory scan.

## Agent Instructions

1. Start with `$sdd-start TASK-5714`; the implementation workflow provisions the feature worktree. Do not implement on dev.
2. Verify predecessors are done in `sdd/tasks/index/wiki-ledger-sqlite-hardening.json` and recheck this task's contracts.
3. Implement only the declared files, preserve other agents' changes, and complete every acceptance gate. Store execution logs under `artifacts/logs/`.
4. Use `parrot sdd task finalize` with real TaskCompletionEvidence and the exact implementation HEAD. The finalizer owns the completion note and active-to-completed move; do not hand-edit them.

## Completion Note

- Task: TASK-5714
- Feature: wiki-ledger-sqlite-hardening
- Implementation SHA: a2eb7b2dde17e1dfc6cce8f7c89f37cffd5a3994
- Closed at (UTC): 2026-11-16T21:56:24+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 743s · Tokens: n/a |
