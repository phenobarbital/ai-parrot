---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [sqlite, wikitoolkit, ledger, concurrency, performance]
docs:
  policy: required
  pages: [wiki/wiki/sqlite-ledger-concurrency.md]
  api_modules:
    - parrot.knowledge.wiki.ledger.store
    - parrot.knowledge.wiki.ledger.log
    - parrot.knowledge.wiki.ledger.index
---

# Feature Specification: Wiki and ledger SQLite hardening

**Feature ID**: FEAT-902
**Date**: 2026-11-16
**Author**: Jesus Lara (requirements), Codex (specification)
**Status**: approved
**Target version**: next minor (release assignment pending)
**Source**: `artifacts/plan_wiki_ledger_sqlite_hardening.md` and the accepted conversation scope.

## 1. Motivation & Business Requirements

### Problem Statement

The LLM wiki and issue ledger share SQLiteWikiStore machinery but use separate databases.
FEAT-557 already supplies aiosqlite, WAL, busy timeouts and BEGIN IMMEDIATE. Ledger reads
nevertheless call sync(), which acquires the writer lock even when events.jsonl has no
new events. Replay also opens a second connection to read its cursor; read_cursor reads
the cursor fields separately and masks every exception as an empty ledger cursor.
The persistent_writer constructor option is currently stored but does not implement
connection reuse. There is no comparative evidence justifying its activation.

### Goals

- Make cursor observations coherent, transactional when required, and explicit on failure.
- Avoid writer-lock acquisition for a provably caught-up ledger after initialization.
- Preserve claim ownership, durable event append, replay and recovery across processes.
- Keep the writer lock until an in-flight append/fsync finishes, including cancellation.
- Measure connection setup, lock wait, transaction, commit, replay and durable-log costs.
- Deliver a dedicated measurement task and decision report for persistent connections.

### Non-Goals

No new database, dependency, broker, connection pool or production persistent writer.
No schema/data migration, altered durability pragma, automatic whole-operation retry,
new ledger protocol, public CLI/MCP response change, replay batching or checkpoint tuning.
These latter optimizations require the measurement evidence delivered here.

## Governing Decisions

<!-- decision-audit: input_digest=sha256:713f3dccd2350793b7b361ed046791c4e9cbf081ef40fb88d0cc184c4550ce2a evaluation_digest=sha256:d21371d8e2c8a4387e1fb4d1d70f81aeeb61699c8556a964efc92698ce0baa2e rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

Retain connection-per-operation and the existing SQLite transaction owner. Implement
the following contracts before considering connection reuse.

**Cursor contract.** Keep read_cursor() returning tuple[int, str | None]. Add
read_cursor_in(conn) with the same result, using the caller's connection without opening,
committing or rolling back it. Fetch both keys in one SELECT; a preceding read-only
schema-presence probe is permitted. An absent table or both absent keys means (0, None).
Exactly one key, a negative/non-integer offset or an empty event id raises the new
LedgerCursorInvalid(ValueError). SQLite, permission and I/O failures propagate unchanged.
_sync_locked uses read_cursor_in(conn); only LedgerCursorInvalid triggers a warning and
the existing full-rebuild path under the owned write transaction. Public read_cursor
and audit do not conceal malformed state. A valid cursor whose event no longer matches
the log continues to trigger the existing rebuild behavior.

**No-op sync contract.** Add a conservative synchronous LedgerLog.probe_cursor(), called
through asyncio.to_thread, returning Literal['current', 'replay', 'uncertain'].
Only standalone sync(conn=None) may take the fast path; sync(conn), claim, close and
unclaim always synchronize through the current write transaction.

The fast path is a bounded observation, not a lock or a cache:

1. Read a coherent cursor C1 through read_cursor(). Invalid cursor means slow path.
2. Probe one opened binary log descriptor. Capture fstat identity/size/mtime_ns/ctime_ns
   before and after; compare the pathname stat to the descriptor before returning.
   At a populated cursor, read at most 4097 bytes at its exact byte offset, require a
   newline-terminated valid LedgerEvent with matching event_id, then inspect one byte
   after that line. Exact matching anchor plus EOF and stable metadata means current;
   any suffix means replay. Do not scan or materialize the tail during the probe.
3. An empty cursor is current only with a stable empty log, or a log observed absent
   throughout the probe; any content means replay. A missing log with a populated
   cursor, mismatch, replacement, truncation, oversized/malformed anchor or partial
   anchor means uncertain. FileNotFoundError caused by replacement selects uncertain;
   permission and other I/O errors propagate. No size-only or mtime-only shortcut.
4. Read C2; return 0 only when the probe is current and C1 == C2. Otherwise enter the
   existing ledger_transaction and reread the current cursor inside it. Never replay
   a tail captured before obtaining the write transaction.

This preserves point-in-time read freshness: an append after the completed probe can
appear on the next read, just as an append after the previous implementation's sync
could. A validated observation is not a promise that no future append will occur.
Same-size replacement and anchor mismatch must not be mistaken for no-op. A replacement
with the same matching anchor and EOF remains equivalent under the existing event-id
cursor contract; detecting arbitrary historical rewrites is outside that contract.
Malformed/trailing partial data selects the slow path, retaining iter_events semantics.

**Cancellation contract.** Add LedgerIndex._append_durably(event) for claim/close/unclaim.
It owns a strongly referenced asyncio task running the existing log.append in a thread.
Shield and drain that task before propagating cancellation, including repeated cancel
requests; retain the surrounding SQLite transaction until append/fsync has settled.
Cancellation takes precedence on return; if append also failed, preserve/log that
failure as its cause without logging event contents. Without cancellation, propagate
the append result/error normally. A cancelled operation may already exist in the log:
rollback the SQLite projection and reconcile on the next sync, never append a retry
event automatically. Cancel-before-dispatch must append nothing. Process death is
handled by durable-log replay, not shielding. No hard timeout may abandon a live append
while releasing the writer lock; a stalled filesystem can therefore delay cancellation.

**Observability contract.** Emit structured DEBUG records through existing loggers,
with event='wiki.sqlite.timing', operation, phase, duration_ms, outcome, pid and db_name
(basename only, not full path). Phases: connection_open, connection_setup, begin_wait,
transaction_body, commit, rollback, log_append, log_fsync, replay, sync_probe.
Applicable counts include applied_events and fast_path; the existing busy-fallback
warning adds event='wiki.ledger.stale_read'. Report failed/cancelled timings as such,
never as successful commits. Log append and fsync timings apply to append_line too.
Use a monotonic clock; guard DEBUG-only work with the logger level. No SQL text, issue
body, actor or event payload in timing records, no metric writes to SQLite, no new
global registry, and no changed return values. Phase timings may overlap; the report
must not sum inclusive phases as independent costs. Logger failures must not change
transaction outcomes. The benchmark captures records in per-process memory and writes
artifacts after the timed interval, avoiding synchronous file logging in the hot path.

### Component Diagram

```text
LedgerService reads -> sync(no connection) -> coherent cursor + bounded log probe
                                           | current, cursor unchanged -> read index
                                           | otherwise -> BEGIN IMMEDIATE -> replay
claim/close/unclaim -> BEGIN IMMEDIATE -> replay -> check ownership
                       -> cancellation-safe durable append -> replay -> commit
SQLiteWikiStore / LedgerLog / LedgerIndex -> timing logs -> measurement harness
```

### Integration Points

| Component | Change | Preserved contract |
|---|---|---|
| LedgerStore | Coherent and in-transaction cursor reads | Existing cursor tuple and transaction context manager |
| LedgerLog | Bounded probe and append/fsync timings | JSONL format, append API, durable source of truth |
| LedgerIndex | No-op preflight and cancellation-safe append | First claim wins; ownership checks; replay order |
| SQLiteWikiStore | Phase timing only | WAL, busy timeout, BEGIN IMMEDIATE, read-only fallback, FTS5 |
| LedgerService | Structured stale-read warning | Existing best-effort reads and CLI/MCP response shapes |

### Data Models and New Interfaces

No persisted model changes. LedgerCursorInvalid is a typed validation error; probe
results are a Literal, not persisted state. The benchmark uses Pydantic v2 models
BenchmarkConfig and BenchmarkReport, with schema_version=1, revision and environment
metadata, workload parameters, per-cell samples/counts/outcomes and invariant results.
Public additions and exact skeletons are specified per module below.

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided contracts | Why not |
|---|---|---|---|
| M1 Cursor consistency | yes | tuple API, one SELECT, typed invalid state, transaction reuse | — |
| M2 No-op synchronization | yes | conservative three-state bounded probe, double cursor read | — |
| M3 Cancellation safety | yes | shield/drain append before releasing writer, no automatic retries | — |
| M4 Timing instrumentation | yes | exact phases/fields and failure behavior above | — |
| M5 Measurement and follow-up | no | fixed matrix, artifacts and decision rubric below | Evidence interpretation needs engineering judgment |
| M6 Documentation | yes | operational guarantees, caveats and measurement instructions | — |

### Module 1: Coherent replay cursor

- **Paths**: ledger/store.py and ledger/index.py under packages/ai-parrot/src/parrot/knowledge/wiki/;
  create packages/ai-parrot/tests/knowledge/wiki/test_ledger_cursor_consistency.py.
- **Depends on**: existing LedgerStore and LedgerIndex only.
- **Responsibility**: Implement the cursor contract and typed recovery path.
- **Interface Skeleton**:

```python
class LedgerCursorInvalid(ValueError):
    """Persisted cursor fields are incomplete or invalid; replay must rebuild explicitly."""

# Existing class verified: packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py:24
class LedgerStore(SQLiteWikiStore):
    async def read_cursor(self) -> tuple[int, str | None]:
        """Read one coherent committed cursor; absent state is empty, invalid state raises."""
    async def read_cursor_in(self, conn: aiosqlite.Connection) -> tuple[int, str | None]:
        """Read the caller's transactional cursor without owning connection lifecycle."""

# Existing method verified: packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py:323
async def _sync_locked(self, conn: aiosqlite.Connection) -> tuple[int, int, str | None]:
    """Read cursor in conn; explicitly rebuild invalid state and replay the current tail."""
```

### Module 2: Avoid no-op writer transactions

- **Paths**: ledger/log.py, ledger/index.py;
  create packages/ai-parrot/tests/knowledge/wiki/test_ledger_sync_fast_path.py.
- **Depends on**: M1, because preflight and locked replay use its cursor/error contract.
- **Responsibility**: Implement the bounded three-state probe and standalone sync fast path.
- **Interface Skeleton**:

```python
# Existing class verified: packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py:10
class LedgerLog:
    def probe_cursor(self, offset: int, last_event_id: str | None) -> Literal["current", "replay", "uncertain"]:
        """Conservatively inspect the cursor anchor and EOF without writing or scanning the tail."""

# Existing method verified: packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py:306
async def sync(self, conn: aiosqlite.Connection | None = None) -> int:
    """Skip the writer only on validated no-op standalone replay; return events applied."""
```

### Module 3: Preserve writer ownership through append cancellation

- **Paths**: ledger/index.py;
  create packages/ai-parrot/tests/knowledge/wiki/test_ledger_append_cancellation.py.
- **Depends on**: existing append and transaction machinery; no semantic dependency on M1/M2.
- **Responsibility**: Use the helper in claim/close/unclaim; prove cancellation and crash recovery.
- **Interface Skeleton**:

```python
# Existing owner verified: packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py:129
async def _append_durably(self, event: LedgerEvent) -> tuple[str, int]:
    """Drain append/fsync under cancellation before allowing the caller's write lock to unwind."""
```

### Module 4: Shared SQLite and ledger phase timings

- **Paths**: wiki/store.py, ledger/log.py, ledger/index.py, ledger/service.py;
  create packages/ai-parrot/tests/knowledge/wiki/test_sqlite_timing.py.
- **Depends on**: M2 and M3 for probe/fast-path and guarded-append timing coverage.
- **Responsibility**: Implement the observability contract without new storage/configuration.
- **Interface Skeleton** (existing signatures unchanged):

```python
# verified: packages/ai-parrot/src/parrot/knowledge/wiki/store.py:1481
async def _open(self, *, writable: bool) -> AsyncIterator[aiosqlite.Connection]:
    """Open a policy-configured connection and observe connection/setup time."""
# verified: packages/ai-parrot/src/parrot/knowledge/wiki/store.py:1853
async def _write(self, operation: str) -> AsyncIterator[aiosqlite.Connection]:
    """Own BEGIN/COMMIT/ROLLBACK and observe phase outcomes without changing semantics."""
# verified: packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py:21
def append(self, event: LedgerEvent) -> tuple[str, int]:
    """Persist an event with existing durability and observe append/fsync latency."""
# verified: packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py:83
def append_line(self, line: str) -> int:
    """Persist a serialized event with existing durability and phase timings."""
# verified: packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py:220
async def _sync_best_effort(self) -> None:
    """Keep best-effort reads; mark a busy fallback as a structured stale-read event."""
```

### Module 5: Dedicated measurement task and persistent-connection follow-up

**Mandatory separate SDD task during decomposition; do not fold it into a test-only task.**

- **Create**: packages/ai-parrot/tests/knowledge/wiki/benchmarks/sqlite_ledger_hardening.py;
  packages/ai-parrot/tests/knowledge/wiki/test_sqlite_benchmark_contract.py;
  sdd/state/FEAT-902/benchmarks/report.md and persistent-connections-followup.md.
- **Depends on**: M4 (transitively M1/M2/M3) for the candidate measurement. Record the baseline
  revision before implementation; the same driver must run against both revisions.
- **Interface Skeleton**:

```python
class BenchmarkConfig(BaseModel):
    """Validated arm, revision, workload, process count, trial, seed and isolated output paths."""
class BenchmarkReport(BaseModel):
    """Versioned samples, metadata, operation outcomes and correctness evidence for one run."""
def run_benchmark(config: BenchmarkConfig) -> BenchmarkReport:
    """Spawn isolated workers against disposable files and return reproducible measured evidence."""
def main() -> int:
    """Run the explicit benchmark CLI; return nonzero for invalid or incomplete evidence."""
```

Driver arguments: --arm baseline|candidate, --revision, --processes 1|4|8,
--workload idle-ledger|mixed-ledger|claim-race|wiki, --lifecycle resident|ephemeral,
--trials (default 3), --warmup (100), --operations (1000 per worker), --seed (902),
--output-dir, --run-timeout-s (default 1800). Ephemeral means a new store/service per
operation in an already-running process; label it CLI-like and exclude interpreter
startup. Resident reuses store/service instances, not connections (both arms still
use connection-per-operation). Spawn processes, never inherit SQLite connections.

Run identical baseline/candidate matrices: 1/4/8 processes × both lifecycles × four
workloads. Idle-ledger repeats get/list/ready on a caught-up index; mixed-ledger uses
80% reads / 20% unique opens with replay; claim-race synchronizes one attempt per
process per fresh issue using barriers; wiki uses 80% page/FTS reads / 20% page upserts
with unique identifiers and existing store APIs verified during task authoring.
Seed 1000 synthetic issues/pages per cell. Keep wiki.db and ledger.db separate, as
production does. All benchmark DBs/logs live under a disposable artifact directory.

Run the driver from the candidate tree against an immutable baseline snapshot at
e5f3f7534876f9b4f56ad1cedc7b4e56176ee568 (or document a later verified pre-change SHA).
Use isolated subprocess source resolution; record actual imported module paths and
fail if an arm imports the wrong checkout. Use existing environments read-only; do not
modify the main environment or run against real .parrot databases. Alternate baseline
and candidate trial order. Record CPU, OS/filesystem/storage, Python, SQLite,
aiosqlite versions, effective pragmas, fixture scale, git SHAs and dirty state.

Baseline phase hooks do not exist: common comparisons are end-to-end latency,
throughput, BUSY/error counts, connection counts and loop lag. Capture actual SQLite
connection attempts with a harness-only wrapper around aiosqlite.connect on both arms.
Use public set_trace_callback for BEGIN/COMMIT counts. Candidate-only phase metrics
must be labelled unavailable on baseline, never zero. Compare timed DEBUG-on runs
with a separate DEBUG-off pass to estimate instrumentation overhead. A 10ms asyncio
heartbeat records scheduling lag, not an assertion that OS scheduling is deterministic.

Report p50/p95/p99 and sample counts by operation/process count/lifecycle, throughput,
begin attempts, fast-path count, connection opens, replay events, BUSY outcomes,
stale-read fallbacks, append/fsync cost, errors, loop lag and WAL size before/after.
Keep failed and successful samples separate. Store raw measurements/logs under
artifacts/logs/FEAT-902/sqlite-hardening/; commit the compact report and manifest of
commands, SHAs and raw-file hashes under sdd/state/FEAT-902/benchmarks/.

After final sync, check projection against a freshly rebuilt index from the same log,
no lost accepted events, one owner per claim-race, no stranded worker/thread and no
integrity errors. Candidate invariant failures block completion. Baseline failures
remain visible evidence; never discard failed trials to improve comparisons.

The follow-up deliverable must say one of **defer**, **run isolated reuse spike** or
**propose production reuse**, with evidence and limitations. Attribute cost to connection
creation/setup versus writer contention/fsync/replay; report regression/improvement
ratios and run-to-run variation. Connection count alone is not a justification. No
promised percentage speedup or arbitrary production SLA is a gate. If results are noisy,
recommend defer and name the missing evidence rather than claim a win. A reuse proposal
must define per-file/per-process ownership, bounded admission of whole transactions,
commit acknowledgments, cancelled/failed transaction cleanup, read connections,
shutdown/drain and a cross-process limitation. This task does NOT implement that proposal
or claim that setting persistent_writer=True measures reuse.

### Module 6: Operational documentation

- **Create**: wiki/wiki/sqlite-ledger-concurrency.md.
- **Depends on**: M5 for measured results and recommendation.
- **Responsibility**: Document no-op freshness, cursor recovery, cancellation outcomes,
  diagnostics and benchmark reproduction; explain the persistent-writer follow-up.
- **Interface Skeleton**: documentation only; no callable interface. Required sections:
  Guarantees, Failure and recovery, Timing fields, Reproduce measurements, Follow-up.

## 4. Test Specification

### Unit Tests

| Behavior | Module | Required evidence |
|---|---|---|
| Cursor pair is coherent | M1 | Peer commits between scheduling points cannot mix cursor versions |
| Own writes visible | M1 | read_cursor_in sees an uncommitted cursor; no extra connection |
| Absence vs corruption | M1 | Missing table/keys handled; partial/invalid keys raise typed error |
| Real failures propagate | M1 | Permission/SQLite I/O errors cannot become (0, None) |
| Probe is bounded and conservative | M2 | Valid EOF, appended tail, malformed/partial anchor, empty/missing file |
| Probe races | M2 | Same-size replacement, truncation, metadata change and cursor C1/C2 change |
| Cancelled durable append | M3 | Controlled append/fsync barriers, repeated cancel, append failure + cancel |
| Timings preserve behavior | M4 | Monotonic nonnegative phases, failures labelled, no payload leakage |
| Driver validity | M5 | Schema, counts, arm import isolation and incomplete-run rejection |

### Integration Tests

Use real temporary WAL files and spawned peer processes with Event/Barrier coordination.
Avoid sleep-based ordering. Test service-level get/list/ready, not just _read().

- After initialization, a caught-up service read finishes while a peer holds the writer
  lock, emits no BEGIN IMMEDIATE, and returns the expected issue state.
- When events are pending, sync still uses the bounded busy policy; a claim blocked at
  BEGIN appends no event. Mutation prechecks never use the no-op shortcut.
- Two successive sync(conn) calls in one transaction observe the advanced cursor and do
  not replay the same event twice; forced invalid/mismatched cursor rebuilds converge.
- Exactly one concurrent claimant succeeds; unauthorized close/unclaim still refuses.
- While append/fsync is gated, cancel its owning mutation and prove a competing writer
  cannot enter until the append completes. Then allow rollback/replay and compare state.
- Kill a child process after fsync but before SQLite commit; restart/sync twice and
  compare the projection with rebuild. This is a process-crash test, not a power-loss test.
- Probe append/rotation races do not skip complete accepted events; no automatic retries
  generate duplicate lifecycle events. Existing malformed-line replay semantics remain.
- Wiki page/FTS results and read-only behavior remain unchanged by phase instrumentation.

### Validation Contract

tests:
- packages/ai-parrot/tests/knowledge/wiki/test_ledger_cursor_consistency.py
- packages/ai-parrot/tests/knowledge/wiki/test_ledger_sync_fast_path.py
- packages/ai-parrot/tests/knowledge/wiki/test_ledger_append_cancellation.py
- packages/ai-parrot/tests/knowledge/wiki/test_sqlite_timing.py
- packages/ai-parrot/tests/knowledge/wiki/test_sqlite_benchmark_contract.py
- tests/knowledge/wiki/test_ledger_store.py
- tests/knowledge/wiki/test_ledger_index.py
- tests/knowledge/wiki/test_ledger_log.py
- tests/knowledge/wiki/test_store_concurrency.py
- tests/knowledge/wiki/test_ledger_fix_lifecycle.py
- tests/knowledge/wiki/test_ledger_shared_log_rotation.py
- packages/ai-parrot/tests/knowledge/wiki/test_ledger_service_reads.py
markers: none

The first five paths are created by this feature; remaining operands are existing
regression coverage. The full benchmark matrix is an explicit M5 evidence gate, not
an automatically collected pytest performance test. Store validation logs in artifacts/logs/.

## 5. Acceptance Criteria

- [ ] AC1: Cursor fields are observed together; in-transaction replay opens no cursor connection.
- [ ] AC2: Invalid cursor is explicit; only its typed error selects rebuild; real DB/I/O errors propagate.
- [ ] AC3: Initialized, caught-up get/list/ready take no writer lock, including with a live peer writer.
- [ ] AC4: Probe is bounded and conservative on replacement, truncation, partial data and cursor races.
- [ ] AC5: Mutation paths retain BEGIN IMMEDIATE, ownership checks and first-claim-wins semantics.
- [ ] AC6: Append/fsync drains before cancellation releases writer ownership; replay recovers durable events.
- [ ] AC7: Phase timings and stale-read evidence are available without SQL/payload exposure or new persistence.
- [ ] AC8: All validation-contract tests pass; FTS5, schema, formats, pragmas and public response shapes remain compatible.
- [ ] AC9: The dedicated measurement task runs and records both full matrices, metadata and all errors/invariants.
- [ ] AC10: persistent-connections-followup.md contains an evidence-backed disposition and proposed next scope.
- [ ] AC11: No production connection reuse, extra dependency or hidden automatic lifecycle-event retry is introduced.
- [ ] AC12: Documentation in §10 exists and describes measured limits and cancellation/recovery behavior.

## 6. Codebase Contract

Verified against base commit **e5f3f7534876f9b4f56ad1cedc7b4e56176ee568**.
Line references below are repository-relative. Revalidate before task blueprints.

### Verified Imports and Existing Signatures

```python
from parrot.knowledge.wiki.store import SQLiteWikiStore, SQLitePragmaPolicy, WikiStoreBusy
# verified definitions: packages/ai-parrot/src/parrot/knowledge/wiki/store.py:1265,279,300
from parrot.knowledge.wiki.ledger.store import LedgerStore
# verified: packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py:24
from parrot.knowledge.wiki.ledger.log import LedgerLog
# verified: packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py:10
from parrot.knowledge.wiki.ledger.index import LedgerIndex
# verified: packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py:129
from parrot.knowledge.wiki.ledger.events import LedgerEvent
# verified: packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py:103
from parrot.knowledge.wiki.ledger.service import LedgerService
# verified: packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py:149
```

| Existing method / property | Exact contract | Verified location |
|---|---|---|
| LedgerStore.ledger_transaction | (self, operation: str) -> AsyncIterator[aiosqlite.Connection] | ledger/store.py:54 |
| LedgerStore.read_cursor | (self) -> tuple[int, str \| None] | ledger/store.py:75 |
| LedgerIndex.sync | (self, conn: "aiosqlite.Connection \| None" = None) -> int | ledger/index.py:306 |
| LedgerIndex._sync_locked | (self, conn: "aiosqlite.Connection") -> tuple[int, int, str \| None] | ledger/index.py:323 |
| LedgerIndex.claim_issue | (self, issue_id: str, claimed_by: str) -> bool | ledger/index.py:445 |
| LedgerLog.append | (self, event: LedgerEvent) -> tuple[str, int] | ledger/log.py:21 |
| LedgerLog.iter_events | (self, from_offset: int = 0) -> Iterator[tuple[LedgerEvent, int]] | ledger/log.py:111 |
| LedgerService._sync_best_effort | (self) -> None, async; catches WikiStoreBusy only | ledger/service.py:220 |

Locations in the table share prefix packages/ai-parrot/src/parrot/knowledge/wiki/.
LedgerIndex stores .store and .log (index.py:139-140); cursor offset is the start of
the last applied event line, not EOF (_write_cursor, index.py:295). LedgerLog.append's
returned byte offset is informational and must not become the replay cursor.

### Integration Points

M1 replaces _sync_locked's call to self.store.read_cursor with read_cursor_in(conn).
M2 wraps only the conn=None branch of sync. M3 replaces the three guarded
asyncio.to_thread(self.log.append, event) sites in claim/close/unclaim. M4 preserves
_write exception mapping and augments _sync_best_effort's existing warning.
LedgerService.from_root/from_dir continue constructing the same store/log/index.

### Does NOT Exist

- LedgerStore.read_cursor_in, LedgerCursorInvalid and LedgerLog.probe_cursor are NEW here.
- LedgerIndex._append_durably is NEW; a bare to_thread call does not drain on cancellation.
- An active persistent writer is absent: _persistent_writer/_writer_conn are only initialized.
- LedgerTxn/LedgerReader are pending in TASK-4380, not available APIs at this base.
- No SQLite multi-process broker or connection pool is introduced or assumed.

### Edit Sites (Blueprint Anchors)

Each MODIFY anchor below was verified with grep -c -F and occurs exactly once.
All attachment anchors below use full repository-relative paths.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py | MODIFY | `    async def read_cursor(self) -> tuple[int, str \| None]:` | packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py:75 | 1 |
| packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py | MODIFY | `    async def sync(self, conn: "aiosqlite.Connection \| None" = None) -> int:` | packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py:306 | 1 |
| packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py | MODIFY | `    def iter_events(self, from_offset: int = 0) -> Iterator[tuple[LedgerEvent, int]]:` | packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py:111 | 1 |
| packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py | MODIFY | `    async def _sync_best_effort(self) -> None:` | packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py:220 | 1 |
| packages/ai-parrot/src/parrot/knowledge/wiki/store.py | MODIFY | `    async def _write(self, operation: str) -> AsyncIterator[aiosqlite.Connection]:` | packages/ai-parrot/src/parrot/knowledge/wiki/store.py:1853 | 1 |
| packages/ai-parrot/tests/knowledge/wiki/test_ledger_cursor_consistency.py | CREATE | — | — | — |
| packages/ai-parrot/tests/knowledge/wiki/test_ledger_sync_fast_path.py | CREATE | — | — | — |
| packages/ai-parrot/tests/knowledge/wiki/test_ledger_append_cancellation.py | CREATE | — | — | — |
| packages/ai-parrot/tests/knowledge/wiki/test_sqlite_timing.py | CREATE | — | — | — |
| packages/ai-parrot/tests/knowledge/wiki/test_sqlite_benchmark_contract.py | CREATE | — | — | — |
| packages/ai-parrot/tests/knowledge/wiki/benchmarks/sqlite_ledger_hardening.py | CREATE | — | — | — |
| sdd/state/FEAT-902/benchmarks/report.md | CREATE | — | — | — |
| sdd/state/FEAT-902/benchmarks/persistent-connections-followup.md | CREATE | — | — | — |
| sdd/state/FEAT-902/benchmarks/manifest.json | CREATE | — | — | — |
| wiki/wiki/sqlite-ledger-concurrency.md | CREATE | — | — | — |

## 7. Implementation Notes & Constraints

Use async database I/O and asyncio.to_thread for blocking log inspection/append only.
No network/LLM operations while owning a write transaction. Preserve existing public
method signatures; additions are additive. Keep existing read-only fallback and
initialization behavior; AC3 applies after schema initialization, not first boot.

Cancellation-safe append does not create a transaction spanning JSONL and SQLite.
The log can survive a SQLite rollback: consumers must reconcile before retrying.
Do not infer atomic regular-file writes from PIPE_BUF; that is a pipe guarantee.
This feature retains the current local-filesystem append contract and tests supported
filesystems; it does not certify network filesystems or universal power-loss durability.

NORMAL in WAL remains the configured SQLite setting; the authoritative ledger log
retains fsync. No blanket durability downgrade or checkpoint change is authorized.
Hotfixing unrelated log formats, ownership policies or HelixDB protocols is out of scope.

### External Dependencies

| Package | Existing declaration | Use |
|---|---|---|
| aiosqlite | >=0.17, packages/ai-parrot/pyproject.toml:209 | Async connections and trace callbacks |
| pydantic | >=2.12.5,<3, same file:54 | Existing events and new benchmark models |
| Python stdlib | >=3.11,<3.14, same file:18 | asyncio, time, os, multiprocessing, statistics |

No installation is required. Existing pytest/pytest-asyncio test patterns apply.

## Decisions

```yaml
schema_version: 1
document_id: wiki-ledger-sqlite-hardening
entries:
  - id: conservative-noop-replay
    statement: Only standalone ledger synchronization may skip its writer transaction after a coherent cursor and bounded log-anchor validation prove no pending work.
    relation: constrains
    about: [knowledge-wiki]
    targets:
      - file:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py
      - file:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py
      - file:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py
    contradicts: []
    supersedes: []
    rationale: Reads should not contend as writers when caught up; mutations still need serialized ownership and replay.
    rejected_alternatives: [size-only freshness checks, skipping synchronization inside claims]
  - id: drain-durable-append
    statement: A cancelled ledger mutation must retain writer ownership until its dispatched durable append has settled, then propagate cancellation and reconcile from the authoritative log.
    relation: requires
    about: [knowledge-wiki]
    targets:
      - file:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py
    contradicts: []
    supersedes: []
    rationale: Cancelling an awaiting coroutine does not stop its append thread and must not release coordination early.
    rejected_alternatives: [unshielded append during a mutation, blind whole-operation retries]
  - id: measure-before-reuse
    statement: This feature preserves connection-per-operation and requires comparative measurement and a follow-up disposition before any production persistent-connection implementation.
    relation: constrains
    about: [knowledge-wiki]
    targets:
      - file:packages/ai-parrot/src/parrot/knowledge/wiki/store.py
    contradicts: []
    supersedes: []
    rationale: Connection setup, writer contention and fsync costs need separate attribution before changing resource lifetime.
    rejected_alternatives: [treating persistent_writer=True as an implemented reuse strategy]
```

## Worktree Strategy

**Isolation: per-spec**, one feature worktree; the implementation engine may allocate
task sub-worktrees. No runtime implementation on dev during spec creation.

Dependency edges: M2 -> M1 (cursor API); M4 -> M2/M3 (timing the new paths);
M5 -> M4 (measurement evidence); M6 -> M5 (document actual results).
M3 has no semantic dependency on M1. Shared ledger/index.py among M1–M4 and
ledger/log.py between M2/M4 require file-level serialization by task scheduling.
Do not add artificial architectural edges merely to express that shared-file constraint.
M5 is parallel:false: it exclusively uses the measurement host/resources and isolated
baseline snapshot while gathering comparable evidence. Other modules have no shared
external-resource mutation. Fixtures never touch the live wiki or ledger.

Cross-feature: FEAT-557 is already present. TASK-4380 (FEAT-670) overlaps the ledger
store/index/service protocol surface but is not a prerequisite. Revalidate its landing
state at decomposition and integration; if it lands first, update this contract before
implementation rather than restore raw-connection interfaces over its protocol refactor.

## Consequences

<!-- decision-audit: input_digest=sha256:713f3dccd2350793b7b361ed046791c4e9cbf081ef40fb88d0cc184c4550ce2a evaluation_digest=sha256:d21371d8e2c8a4387e1fb4d1d70f81aeeb61699c8556a964efc92698ce0baa2e rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- none

Coverage:
- Subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, skills, tools
- Unmapped tags: concurrency, ledger, performance, sqlite, wikitoolkit
- Targets resolved: 4/4
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [
      "bots",
      "clients",
      "config",
      "flows",
      "knowledge-graphindex",
      "knowledge-pageindex",
      "knowledge-wiki",
      "memory",
      "skills",
      "tools"
    ],
    "targets_resolved": 4,
    "targets_total": 4,
    "unmapped_tags": [
      "concurrency",
      "ledger",
      "performance",
      "sqlite",
      "wikitoolkit"
    ]
  },
  "diagnostics": [],
  "evaluation_digest": "sha256:d21371d8e2c8a4387e1fb4d1d70f81aeeb61699c8556a964efc92698ce0baa2e",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:713f3dccd2350793b7b361ed046791c4e9cbf081ef40fb88d0cc184c4550ce2a",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {
      "adr:doc:171b17ccd26bdbd2d71040746b22371a335d364d": "b22c79daae2a187f2091ea23449825e8769e2c07",
      "adr:doc:34394c36f5bf140678b8e17d43c3628e3d2c1440": "3fa15352d0e9ed972bd5de7ac1fd60e06906e60b",
      "adr:doc:666d8f740c695673063f76777db7b7b0e9d95a2e": "47f1bebe56724843f6c0981f67bbba72917b4b0b",
      "adr:doc:87781d348dff80cbfb25c253989a8940badd08d1": "49458f64f4bb614a9ff42750b53d9caa806f81a0",
      "adr:doc:89e808b78adee5c727e047ac239817bfd29e5cfe": "9feeb90ec52cb53395d978a3b946323a7b9072ab",
      "adr:doc:96dabb33251cd210186d7ab5c456ded102a4b025": "b537050f62f77a85b651af8c2595f4dc7fd4cebe",
      "adr:doc:c3c29b415ba46e730ee37c6fc520914a1905d022": "0cd9cc9f082b9d988da023e3886d310f8eed8eae",
      "adr:doc:c6b0e17a26d4b1ae2be8569a33db9a3aeedc0fbd": "804496ec336c99570df5502580ff980a38f56bfc",
      "adr:doc:e7c5ae770b06db3b35cdd4cba93001a58bfa7bef": "394f4656c71618a256427d81350fdc32335fa791"
    },
    "rules_version": 1,
    "structural_revision": "sha256:6327295d71e6e8d324264633215b63e8019ac5c514cefc05ee7d8e9c34ceb6c6",
    "taxonomy_digest": "65548b9a71329b13ab44f4904dff99814e1aac0da4bb2b58171a7201e3a9ba39"
  },
  "status": "pass"
}
```

## 8. Open Questions

- [x] Keep SQLite + aiosqlite — resolved by the user; no new dependency.
- [x] Include ledger issues — resolved by the user; preserve its durable-log semantics.
- [x] Persistent connections — explicit measurement/follow-up task; no production reuse here.
- [x] Target release/status — next minor, review; no blocking release-specific constraint supplied.
- [ ] Does measured connection/setup cost justify a persistent-writer proposal? Owner: M5;
  answered in its report with defer/spike/propose, not a blocker for implementation.

## 9. Design Research Cross-Check

Status: skipped (direct request based on a local plan, with no accepted brainstorm/proposal
or completed intake artifact satisfying the optional independent-research precondition).
Code anchors were reverified against the base; no independent design review is claimed.

## 10. Documentation

- **Policy**: required.
- **Create** wiki/wiki/sqlite-ledger-concurrency.md with guarantees, recovery, measurement
  commands and results, and the persistent-connection decision. Link the M5 reports.
- **API modules**: parrot.knowledge.wiki.ledger.store, .log and .index; document the
  new helper/error contracts and the point-in-time nature of the fast path.

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-16 | Codex | Initial spec from the accepted plan; dedicated M5 measurement task |
