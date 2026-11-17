# TASK-5713: Coherent transactional ledger cursor and explicit recovery

**Feature**: FEAT-902 - Wiki and ledger SQLite hardening
**Spec**: `sdd/specs/wiki-ledger-sqlite-hardening.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: No predecessor; creates LedgerCursorInvalid/read_cursor_in and modifies ledger/store.py plus ledger/index.py. The independent benchmark driver uses existing public APIs and writes different files.

## Context

Implement spec M1 and AC1/AC2/AC8. The two cursor fields must describe the same committed state, and replay must observe its own uncommitted cursor. Real storage failures must not be converted to an empty cursor.

## Scope

- Add LedgerCursorInvalid and read_cursor_in(conn); keep read_cursor()'s tuple result and signature.
- Read the two data keys in one SELECT, with an optional schema-presence probe; distinguish empty state, incomplete/invalid values, and DB/I/O failure.
- Use the caller connection in _sync_locked; rebuild only for LedgerCursorInvalid, preserving mismatch recovery in _apply_from.
- Add focused WAL, own-write, error-propagation and repeated-sync tests.

**NOT in scope**: No no-op probe, connection reuse, timing instrumentation, schema change, log format change or LedgerTxn refactor.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py` | MODIFY | Scoped implementation |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py` | MODIFY | Scoped implementation |
| `packages/ai-parrot/tests/knowledge/wiki/test_ledger_cursor_consistency.py` | CREATE | Focused validation |

## Codebase Contract (Anti-Hallucination)

Verified against base `0eb46c010bf33b05fabc924253ced5a3d21b02fb` on 2026-11-16. Existing signatures and exact edit anchors were re-read; dependency-produced symbols are explicitly distinguished from existing ones. Recheck them after predecessor commits. If a required import or interface differs, stop and report drift instead of guessing.

### Verified Imports

```python
import asyncio
import sqlite3
from pathlib import Path
import aiosqlite
import pytest
from parrot.knowledge.wiki.store import SQLiteWikiStore, SQLitePragmaPolicy
from parrot.knowledge.wiki.ledger.store import LedgerStore
from parrot.knowledge.wiki.ledger.log import LedgerLog
from parrot.knowledge.wiki.ledger.index import LedgerIndex
from parrot.knowledge.wiki.ledger.events import LedgerEvent
```

Stdlib imports and installed pytest/aiosqlite/Pydantic were verified in the activated repository environment; no new dependency is authorized. Imports of new symbols belong to their named producer below and must be verified after it lands.

### Existing Signatures and Dependency Interfaces

- packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py:24,54,75: LedgerStore inherits SQLiteWikiStore; ledger_transaction(operation: str) yields aiosqlite.Connection; read_cursor() -> tuple[int, str | None].
- packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py:295,323,410: _write_cursor(conn, line_start: int, event_id: str) writes both keys; _sync_locked(conn) returns (applied, offset, id); _rebuild_locked_with_cursor(conn) returns that same triple.
- packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py:21: append(event: LedgerEvent) -> tuple[str, int].
- packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py:103: LedgerEvent(kind, subject, actor, payload) generates an id when absent.
- packages/ai-parrot/src/parrot/knowledge/wiki/store.py:279,1265,1853: existing policy and write transaction ownership.
- New LedgerCursorInvalid import is authored in this task, then imported at runtime by ledger/index.py. Avoid import cycles; store.py does not import index.py.

### Does NOT Exist

- LedgerCursorInvalid and LedgerStore.read_cursor_in are new in this task.
- LedgerTxn/LedgerReader are still absent; do not implement TASK-4380.
- A reusable writer connection is not implemented by persistent_writer=True.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_ledger_cursor_consistency.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py#LedgerStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py#LedgerStore.read_cursor",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py#LedgerStore.ledger_transaction",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py#LedgerIndex",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py#LedgerIndex._sync_locked",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py#LedgerIndex._write_cursor",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py#LedgerIndex._rebuild_locked_with_cursor",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py#LedgerLog",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py#LedgerLog.append",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py#LedgerEvent",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLitePragmaPolicy",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore._write"
  ]
}
```

## Implementation Notes

Keep the existing SQLite + aiosqlite stack, separate wiki/ledger databases and connection-per-operation lifecycle. Preserve asynchronous I/O and existing transaction ownership; offload blocking file work. No new dependency, schema migration or persistent connection is authorized. Tests use disposable state only.

Blueprint gaps below are bounded authoring instructions, not deliverable code. Complete all marked branches and assertions; never ship stubs. A CREATE block is a whole-file starting point and a MODIFY block attaches only to the quoted owner; preserve surrounding and predecessor changes.

## Implementation Blueprint

### Steps (in order)

1. Implement the typed cursor reader first — one SELECT prevents mixed generations; absent schema is different from storage failure.
2. Wire _sync_locked to read_cursor_in(conn) — the caller transaction must see its cursor writes and own recovery.
3. Test repeated replay and peer commits with controlled synchronization — a final-state-only assertion cannot detect mixed snapshots.

### `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py` (MODIFY)

Verified attachment anchor at `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py:75`; exact occurrence count **1** on authoring base `0eb46c010bf33b05fabc924253ced5a3d21b02fb` (recheck after dependencies land):

```text
    async def read_cursor(self) -> tuple[int, str | None]:
```

```python
# Existing LedgerStore remains intact. Insert the exception above the class.
class LedgerCursorInvalid(ValueError):
    """Persisted cursor fields are incomplete or invalid."""

# Replace read_cursor and add read_cursor_in INSIDE LedgerStore.
async def read_cursor(self) -> tuple[int, str | None]:
    """Return one coherent cursor; propagate real database and I/O failures."""
    async with self._read() as conn:
        return await self.read_cursor_in(conn)

async def read_cursor_in(self, conn: aiosqlite.Connection) -> tuple[int, str | None]:
    """Read the supplied transaction without owning its lifecycle."""
    # FILL IN: schema presence probe, single data SELECT and validation (AC1/AC2).
    # Both absent -> (0, None); partial/negative/non-integer/empty id -> typed error.
    # Never catch arbitrary Exception/sqlite errors as empty state.
    raise NotImplementedError
```

Retain the tuple API while making the transaction boundary explicit. The scaffolding's unfinished reader must be completed, not shipped.

### `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py` (MODIFY)

Verified attachment anchor at `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py:306`; exact occurrence count **1** on authoring base `0eb46c010bf33b05fabc924253ced5a3d21b02fb` (recheck after dependencies land):

```text
    async def sync(self, conn: "aiosqlite.Connection | None" = None) -> int:
```

```python
# Add alongside imports, after LedgerCursorInvalid exists in ledger/store.py.
from parrot.knowledge.wiki.ledger.store import LedgerCursorInvalid

# Within LedgerIndex, replace only _sync_locked's cursor acquisition/recovery.
async def _sync_locked(self, conn: "aiosqlite.Connection") -> tuple[int, int, str | None]:
    """Read this transaction's cursor and explicitly rebuild malformed state."""
    try:
        offset, last_event_id = await self.store.read_cursor_in(conn)
    except LedgerCursorInvalid:
        # FILL IN: log a payload-free warning, then preserve rebuild's tuple (AC2).
        return await self._rebuild_locked_with_cursor(conn)
    return await self._apply_from(conn, offset, last_event_id)
# Update stale comments describing read_cursor's separate-connection workaround.
# Leave sync's standalone writer behavior unchanged in this task.
```

The verified sync anchor identifies the adjacent replay section. Invalid cursor recovery belongs inside the already-owned write transaction.

### `packages/ai-parrot/tests/knowledge/wiki/test_ledger_cursor_consistency.py` (CREATE)

```python
"""FEAT-902 coherent cursor and transactional replay contracts."""
from pathlib import Path
import asyncio
import sqlite3
import aiosqlite
import pytest
from parrot.knowledge.wiki.ledger.store import LedgerCursorInvalid, LedgerStore
from parrot.knowledge.wiki.ledger.index import LedgerIndex
from parrot.knowledge.wiki.ledger.log import LedgerLog
from parrot.knowledge.wiki.ledger.events import LedgerEvent
from parrot.knowledge.wiki.store import SQLitePragmaPolicy

@pytest.fixture
def store(tmp_path: Path) -> LedgerStore:
    """Own a temporary ledger using a bounded test busy timeout."""
    return LedgerStore(str(tmp_path / "ledger.db"), sqlite_policy=SQLitePragmaPolicy(busy_timeout_s=1))

@pytest.mark.asyncio
async def test_cursor_pair_is_one_snapshot(store: LedgerStore) -> None:
    """Controlled peer commits cannot produce a mixed cursor pair."""
    # FILL IN: coordinate two WAL connections and assert coherent observations (AC1).
    raise NotImplementedError

@pytest.mark.asyncio
async def test_transaction_reads_own_cursor(store: LedgerStore) -> None:
    """Repeated sync(conn) reads the transaction's own advanced cursor."""
    # FILL IN: append/replay twice in one transaction; count connections/events (AC1).
    raise NotImplementedError

@pytest.mark.asyncio
async def test_cursor_errors_are_explicit(store: LedgerStore) -> None:
    """Absent, invalid and failed storage have different outcomes."""
    # FILL IN: parameterize absent table/keys, partial/invalid state and DB failures (AC2).
    raise NotImplementedError
# FILL IN: add rebuild-convergence coverage and deterministic peer coordination.
```

Keep fixtures local so this task does not acquire exclusivity through conftest changes.

### FILL IN Checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py` — complete its marked implementation/prose and boundary cases using Scope, Acceptance Criteria and Test Specification.
- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py` — complete its marked implementation/prose and boundary cases using Scope, Acceptance Criteria and Test Specification.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/test_ledger_cursor_consistency.py` — complete its marked implementation/prose and boundary cases using Scope, Acceptance Criteria and Test Specification.
- [ ] Verify imports, types, exact attachment anchors and dependency outputs in the implementation checkout.
- [ ] Remove every unfinished scaffold from delivered files; inspect the scoped diff and run all mandatory gates.

## Acceptance Criteria

- [ ] AC1: A single data SELECT reads both keys; read_cursor_in never opens/commits/rolls back a connection.
- [ ] AC2: Absent table or both absent keys returns (0, None); partial keys, invalid offset or empty id raises LedgerCursorInvalid.
- [ ] AC3: SQLite/I/O/permission errors propagate; only typed invalid cursor triggers _sync_locked rebuild.
- [ ] AC4: Two sync(conn) calls see own writes, preserve start-of-last-line semantics, and do not duplicate reductions.
- [ ] AC5: Existing signatures, ownership checks and schema remain compatible; focused tests pass.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_ledger_cursor_consistency.py -q`

## Test Specification

Use temporary WAL databases with independent connections; coordinate a peer commit between scheduling points and assert no mixed pair. Spy on connection creation to prove read_cursor_in opens none. Inject read errors separately from malformed stored values. Compare rebuild and repeated sync outputs.

Run the task-specific commands above. The feature-wide regression contract is cached in the per-spec index and runs at its configured SDD gates; do not replace these focused checks with bare pytest or a directory scan.

## Agent Instructions

1. Start with `$sdd-start TASK-5713`; the implementation workflow provisions the feature worktree. Do not implement on dev.
2. Verify predecessors are done in `sdd/tasks/index/wiki-ledger-sqlite-hardening.json` and recheck this task's contracts.
3. Implement only the declared files, preserve other agents' changes, and complete every acceptance gate. Store execution logs under `artifacts/logs/`.
4. Use `parrot sdd task finalize` with real TaskCompletionEvidence and the exact implementation HEAD. The finalizer owns the completion note and active-to-completed move; do not hand-edit them.

## Completion Note

- Task: TASK-5713
- Feature: wiki-ledger-sqlite-hardening
- Implementation SHA: fffb02bb676bc6754cc5c91ebf018287b09afc90
- Closed at (UTC): 2026-11-16T21:40:18+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 430s · Tokens: n/a |
