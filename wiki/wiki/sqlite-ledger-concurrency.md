---
title: SQLite concurrency for wiki and ledger
summary: Transactional cursor reads, conservative synchronization and durable cancellation.
---

# SQLite concurrency for wiki and ledger

## Purpose
The wiki plane (`wiki.db`) and the work ledger (`ledger.db`) are separate SQLite databases with
separate files, stores and writer locks. Every operation opens its own aiosqlite connection and closes
it when done (connection-per-operation); FEAT-902 keeps that lifecycle. The feature hardens the ledger
side: a transactionally coherent cursor, a conservative no-op synchronization path, cancellation-safe
appends and opt-in timing diagnostics. It adds no dependency, schema migration or persistent connection.

## Public API
- [LedgerStore](ref:parrot.knowledge.wiki.ledger.store.LedgerStore)
- [LedgerLog](ref:parrot.knowledge.wiki.ledger.log.LedgerLog)
- [LedgerIndex](ref:parrot.knowledge.wiki.ledger.index.LedgerIndex)

Symbols added by FEAT-902, all in the modules above:
- `LedgerStore.read_cursor()` returns one coherent `(byte_offset, last_event_id)` and propagates real
  database and I/O failures. `LedgerStore.read_cursor_in(conn)` reads the same cursor inside a
  caller-owned connection or transaction without owning its lifecycle.
- `LedgerCursorInvalid` (a `ValueError`, in `parrot.knowledge.wiki.ledger.store`) is raised when the stored
  cursor is incomplete (only one of the two keys), has a non-integer or negative offset, or an empty event id.
  A missing table or no cursor keys at all is the valid empty cursor `(0, None)`.
- `LedgerLog.probe_cursor(offset, last_event_id)` is a bounded, read-only check returning `"current"`,
  `"replay"` or `"uncertain"`. It is only an observation: it never grants ownership of the log.
- `LedgerIndex._append_durably(event)` is internal (not public API). Claim, close and unclaim use it.

## Configuration & Parameters
No new runtime settings. The existing SQLite policy (WAL, busy timeout, writer serialization through
`_write`) and the log's fsync-on-append durability are unchanged. Timing records are emitted only when the
logger is enabled for DEBUG.

## Usage Examples
Pass the path of an initialized ledger database to this async function.
<!-- feat902:cursor-example -->
```python
from pathlib import Path
from parrot.knowledge.wiki.ledger.store import LedgerStore

async def read_ledger_cursor(db_path: Path) -> tuple[int, str | None]:
    """Read one coherent cursor without changing its transaction lifecycle."""
    store = LedgerStore(str(db_path))
    return await store.read_cursor()
```

A malformed stored cursor raises `LedgerCursorInvalid`; it is never silently reset to the empty cursor
by `read_cursor()`.

## Guarantees
- **Cursor coherence.** Offset and event id are read in one statement scope and validated together, so a
  partial cursor is reported instead of being interpreted as a position.
- **Bounded no-op observation.** `LedgerIndex.sync()` without a connection first reads the cursor, probes the
  log (stat, anchor check, EOF) and re-reads the cursor. Only if the probe says `"current"` and both cursor
  reads agree does it return `0` without taking the writer lock. Any other outcome (`"replay"`, `"uncertain"`,
  an invalid cursor, a changed cursor) falls through to the locked path.
- **Serialized mutations.** Every mutation still runs inside one write transaction, so SQLite writers on one
  database are serialized. First claim in log order wins; `claim_issue` still syncs inside its transaction.
- **Cancellation.** Once an append has been dispatched to a worker thread, cancelling the caller waits for the
  append and its fsync to finish, then re-raises `CancelledError`. The event is therefore not half-written
  from the caller's point of view.

## Failure and recovery
- **Invalid cursor.** Under the writer lock `_sync_locked` logs a warning and rebuilds the materialized
  projection from the log, then writes a fresh cursor. The log is the source of truth.
- **Real database errors** (locked, corrupt, unreadable) are not treated as an invalid cursor; they propagate.
  A busy writer propagates `WikiStoreBusy`.
- **Cancellation drain.** If the drained append itself fails, the original `CancelledError` is raised with the
  append error as its cause.
- **Replay.** When the log is ahead of the cursor, the next locked sync applies the suffix; replay is
  idempotent.
- **Crash window.** An event can be durable in the log before the projection and cursor commit. The next sync
  replays it from the stored cursor, so the projection converges. The projection is not committed atomically
  with the log append.

## Timing and diagnostics
At DEBUG level, `logging` records named `wiki.sqlite.timing` carry `operation`, `phase`, `duration_ms`,
`outcome` (`success`, `error`, `cancelled`), `pid`, `db_name` and phase-specific counts (for example
`fast_path`, `applied_events`). Phases seen in the measured run: `begin_wait`, `connection_open`,
`connection_setup`, `sync_probe`, `log_append`, `log_fsync`, `replay` and `commit`. Phases are inclusive and
overlap (`connection_setup` contains `connection_open`), so they must not be summed. No ledger content is
logged. When a read-side sync is skipped because the writer lock is busy, `LedgerService` emits a WARNING
`wiki.ledger.stale_read` with `outcome=busy`, and the read is served from a possibly stale index.

## Measurements
Baseline `e5f3f7534876f9b4f56ad1cedc7b4e56176ee568` versus candidate
`01bbdd2ff060b529fb6450dcdcede7c261974295`: 48 cells (1/4/8 processes, resident/ephemeral, four workloads),
three trials each, all complete, every invariant true, zero errors or BUSY outcomes.

- There is **no uniform speedup**. Some cells improve and others regress, with large trial-to-trial variance.
- Clear wins: idle-ledger at 8 processes (resident 472 vs 332 ops/s, ephemeral 456 vs 339 ops/s) because the
  fast path removes BEGIN attempts (0 vs 8000 per trial); claim-race ephemeral at 4 processes (p50 17.0 vs
  49.6 ms); mixed-ledger ephemeral at 8 processes (p99 68.9 vs 136.0 ms).
- Regressions or unclear: idle-ledger 1 process ephemeral (43.8 vs 91.3 ops/s); mixed-ledger resident at
  4 processes (p99 109.0 vs 54.7 ms); event-loop lag is higher in the candidate for mixed-ledger.
- **DEBUG-off overhead was not measured.** The benchmark driver always attaches its own DEBUG handler and
  cannot disable it, so the cost of the instrumentation itself is unknown. The evidence is marked incomplete.
- The host was not exclusive (a concurrent worker was running), so absolute numbers are indicative only.

Reproduce with `packages/ai-parrot/tests/knowledge/wiki/benchmarks/sqlite_ledger_hardening.py`
(`--arm`, `--revision`, `--source-root`, `--processes`, `--workload`, `--lifecycle`, `--trials`,
`--warmup`, `--operations`, `--seed`, `--output-dir`, `--run-timeout-s`). Full tables, per-cell hashes and
the manifest are in the linked report and `manifest.json`.

## Persistent-connection follow-up
Recorded disposition: **defer**. Keep connection-per-operation. Under claim-race contention `begin_wait` p50
is 34.3 ms (4 processes) and 54.3 ms (8 processes) versus 5.7 and 5.9 ms for `connection_setup`, so writer
wait, not connection setup, dominates. Most measured gain came from the sync fast path, not connection reuse.
Reopen only after a full DEBUG-off re-measurement on an exclusive host shows setup as a dominant share.

Three things must not be conflated: SQLite **writer serialization** (one writer per database file, always),
**service reuse** (one `LedgerService`/store object serving many calls) and **actual connection reuse**
(keeping an aiosqlite connection open across operations). FEAT-902 delivers none of the connection reuse;
the store object may be reused but each operation still opens its own connection. Lower connection counts in
the claim-race cells are not evidence of a reuse benefit.

## Gotchas
- Single writer per database: heavy mutation traffic queues on the writer lock regardless of process count.
- Cross-process contention is real; fast-path hits depend on the cursor not moving between the two reads.
- The `ledger_state` table is created lazily on the first write transaction; reading before that returns
  the empty cursor.
- Connections are not shared between processes or tasks; do not hold one across operations.
- A cancelled append can delay cancellation by the duration of the fsync, by design.
- No automatic retry is added: a busy writer surfaces as `WikiStoreBusy` or a stale read warning.

## Related
- [Measurement report](../../sdd/state/FEAT-902/benchmarks/report.md)
- [Follow-up decision](../../sdd/state/FEAT-902/benchmarks/persistent-connections-followup.md)
