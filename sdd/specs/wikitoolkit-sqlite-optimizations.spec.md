---
type: feature
base_branch: dev
---

# Feature Specification: wikitoolkit SQLite concurrency hardening

**Feature ID**: FEAT-557
**Date**: 2026-09-14
**Author**: Jesus Lara (brainstorm drafted with Claude; spec drafted with Codex)
**Status**: approved
**Target version**: next minor (release assignment pending)

---

## 1. Motivation & Business Requirements

### Problem Statement

The SQLite wiki retrieval plane (`.parrot/wiki/wiki.db`) is shared by resident MCP servers, SDD agents, one-shot
CLI commands, the post-commit `upsert`, and long-running `build` commands. WAL mode alone does not make concurrent
writers safe: connections use SQLite's implicit default timeout, write transactions are deferred, and `_migrate()`
performs an unconditional version update and commit on every connection. Thus pure readers compete for the one writer
lock and a read-then-write transaction can fail with `SQLITE_BUSY_SNAPSHOT` without consulting the busy handler.

### Goals

- Preserve the existing public `BaseWikiStore` API and existing wiki behaviour; do not change schema or rewrite data.
- Ensure pure reads on an already-migrated SQLite plane issue no write statement.
- Bound writer-lock acquisition with an explicit, configurable 15-second default SQLite busy timeout.
- Make every SQLite writer start its transaction with `BEGIN IMMEDIATE`; normalize an exhausted busy wait at that
  boundary to a typed, actionable error.
- Apply safe SQLite connection pragmas, provide opt-in memory-oriented performance pragmas, checkpoint WAL after the
  long `build` and `ingest` writers, and expose effective SQLite settings through `wikitoolkit status`.
- Extend the synchronous `SourceCollectionManager` with the same timeout and explicit write-transaction policy.

### Non-Goals (explicitly out of scope)

- No work-ledger implementation, second lock, or redesign of `wiki_write_lock` / `flock`.
- No schema revision, database rewrite, SQLite replacement, single-writer broker, or shadow-build file swap.
- No checkpoint after `upsert --changed`; it is a short post-commit path and WAL autocheckpoint remains sufficient.
- No mandatory mmap/cache/temp-store tuning; those stay opt-in to avoid N agents mapping excessive memory.

---

## 2. Architectural Design

### Overview

Add a connection-policy layer inside `SQLiteWikiStore`. `SQLitePragmaPolicy` owns timeout and pragma decisions.
`_open()` creates a connection with `timeout=` and autocommit (`isolation_level=None`), applies the correct safe subset
of pragmas, and retains the current read-only ladder. `_read()` is the only route for reads and cannot begin a write.
`_write(operation)` runs migration once per store instance, executes `BEGIN IMMEDIATE` before yielding, commits on
success and rolls back on failure. SQLite busy codes 5 and 517 occurring at the begin boundary become `WikiStoreBusy`.

Migration becomes read-first: it probes table metadata and schema version before opening a writer transaction, and only
writes when a column or version actually differs. An `asyncio.Event`, guarded by the existing `_init_lock`, suppresses
the post-success per-connection migration probe without becoming process-global. An optional persistent writer remains
off by default; connection-per-call remains the standard path and preserves read-only fallback behaviour.

`checkpoint(truncate=True)` is a concrete `SQLiteWikiStore` capability (not a `BaseWikiStore` requirement). It runs
after `build` and `ingest`, observes whether `TRUNCATE` was blocked by readers, falls back to `PASSIVE`, logs the
outcome, and never turns an otherwise successful long write into a CLI failure.

### Component Diagram

```text
WikiProjectConfig
  └─ sqlite_busy_timeout / sqlite_performance_pragmas
       ├─ create_wiki_store / CLI / toolkit / sync / execution / federation
       │    └─ SQLiteWikiStore(SQLitePragmaPolicy)
       │         ├─ _read() ───────────────→ read-safe connection
       │         └─ _write(operation) ────→ BEGIN IMMEDIATE → WikiStoreBusy
       └─ SourceCollectionManager ────────→ sqlite3 timeout + explicit writes

CLI build / ingest ──→ SQLiteWikiStore.checkpoint() ──→ status sqlite block
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `SQLiteWikiStore` | modifies | Replaces the all-purpose `_connect()` policy with policy-aware read/write paths while retaining current read-only fallback semantics. |
| `SourceCollectionManager` | modifies | Adds `busy_timeout` constructor kwarg and explicit write transactions for its SQLite paths. |
| `WikiProjectConfig` | extends | Adds validated persisted keys `sqlite_busy_timeout` and `sqlite_performance_pragmas`. |
| `create_wiki_store()` and construction call sites | plumbing | Forward SQLite policy/config only for SQLite backend; other backends remain unchanged. |
| CLI `build`, `ingest`, `upsert`, `status` | modifies | Checkpoint only long writers; busy in `upsert` is a soft skip; status reports effective policy. |
| Federation read-only resolver | plumbing | Read-only foreign SQLite stores receive busy timeout but never write pragmas or migrate. |

### Data Models

```python
class SQLitePragmaPolicy(BaseModel):
    """Validated SQLite connection policy for one wiki plane."""

    busy_timeout_s: float = Field(default=15.0, ge=1.0, le=120.0)
    performance_pragmas: bool = False
    journal_size_limit: int = 67_108_864


class WikiStoreBusy(sqlite3.OperationalError):
    """Writer lock was not acquired within the configured busy timeout."""

    db_path: Path
    operation: str
    waited_seconds: float
```

`WikiProjectConfig` gains `sqlite_busy_timeout: float = Field(default=15.0, ge=1.0, le=120.0)` and
`sqlite_performance_pragmas: bool = False`. Existing `.parrot/wiki.json` files deserialize unchanged.

### New Public Interfaces

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
class SQLiteWikiStore(BaseWikiStore):
    def __init__(
        self,
        db_path: str | Path,
        wiki_name: str = "",
        *,
        read_only: bool = False,
        sqlite_policy: SQLitePragmaPolicy | None = None,
        persistent_writer: bool = False,
    ) -> None:
        """Create a SQLite plane with the supplied, validated connection policy."""

    async def checkpoint(self, truncate: bool = True) -> dict[str, int | bool]:
        """Attempt a WAL checkpoint; log reader-blocked truncation without raising."""


class SourceCollectionManager:
    def __init__(..., busy_timeout: float = 15.0, ...) -> None:
        """Create a source manager whose SQLite connections honor busy_timeout."""
```

`checkpoint()` deliberately stays concrete to `SQLiteWikiStore`; adding it to the abstract backend contract would
force unrelated backends to implement SQLite-only behaviour.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: SQLite connection policy | yes | `SQLitePragmaPolicy`, `WikiStoreBusy`, `_open`/`_read`/`_write`, autocommit, `BEGIN IMMEDIATE`, read-first migration, concrete `checkpoint()`. | — |
| M2: Sync source manager | yes | `busy_timeout`, `sqlite3.connect(timeout=..., isolation_level=None)`, explicit begin/commit/rollback for SQLite writes. | — |
| M3: Config and construction plumbing | yes | Two config fields; forward policy only through known SQLite construction paths, including read-only federation timeout. | — |
| M4: CLI observability and recovery | yes | Checkpoint after build/ingest only; `upsert` soft-skips `WikiStoreBusy`; status returns/renders sqlite block. | — |
| M5: Tests and evidence | yes | Unit tests plus marked slow multiprocess contention test; deterministic artifact log. | — |

### Module 1: SQLite store connection policy

- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/store.py`
- **Responsibility**: Centralize SQLite connection setup and transaction ownership without changing the current
  `BaseWikiStore` public write/read methods or read-only permission rules.
- **Depends on**: Existing `_init_lock`, `_connect_readonly`, `_connect_immutable`, `_migrate`, and `BaseWikiStore`.
- **Interface Skeleton**:
  ```python
  class WikiStoreBusy(sqlite3.OperationalError):
      """Raised only when BEGIN IMMEDIATE exhausts the SQLite busy timeout."""

  @asynccontextmanager
  async def _read(self) -> AsyncIterator[aiosqlite.Connection]:
      """Yield a read-safe connection; never migrate or issue write pragmas."""

  @asynccontextmanager
  async def _write(self, operation: str) -> AsyncIterator[aiosqlite.Connection]:
      """Acquire BEGIN IMMEDIATE, then commit or rollback exactly once."""

  async def checkpoint(self, truncate: bool = True) -> dict[str, int | bool]:
      """Attempt TRUNCATE then PASSIVE fallback; never raise for live readers."""
  ```

### Module 2: Source manifest SQLite policy

- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/sources.py`
- **Responsibility**: Apply the configured busy handler and explicit immediate write transactions to source-manager
  initialization/migration and `_upsert` / `_upsert_many` SQLite writes while preserving JSON and ArangoDB branches.
- **Depends on**: Module 1's error policy only where callers need consistent message mapping; it does not depend on
  async connection internals.
- **Interface Skeleton**:
  ```python
  def _connect(self) -> sqlite3.Connection:
      """Open SQLite with configured timeout, autocommit, and row_factory."""

  @contextmanager
  def _write(self, operation: str) -> Iterator[sqlite3.Connection]:
      """Run BEGIN IMMEDIATE / COMMIT and rollback on failure."""
  ```

### Module 3: Configuration and factory plumbing

- **Paths**: `packages/ai-parrot/src/parrot/knowledge/wiki/project.py`, `store.py`, `cli.py`, `toolkit.py`, `sync.py`,
  `execution.py`, `federation.py`
- **Responsibility**: Validate, persist, and forward the two SQLite settings at every existing SQLite store/manager
  construction site; never leak SQLite kwargs into memory, ArangoDB, or satellite backend factories.
- **Depends on**: Module 1 and Module 2 policy signatures.

### Module 4: CLI checkpoint, busy handling, and status

- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`
- **Responsibility**: Call concrete SQLite `checkpoint()` after successful build and ingest while still inside the
  existing writer-lock scope; map `WikiStoreBusy` during `upsert` to its existing non-failing skip semantics; append a
  backward-compatible `sqlite` object/block with journal mode, busy timeout milliseconds, synchronous, journal size
  limit, and enabled optional pragmas.
- **Depends on**: Module 1 and Module 3.

### Module 5: Concurrency and regression tests

- **Path**: `packages/ai-parrot/tests/knowledge/wiki/test_store_concurrency.py` (new) and focused existing wiki tests
- **Responsibility**: Prove transaction, migration, read-only, CLI, and multi-process guarantees without changing
  existing test contracts.
- **Depends on**: Modules 1–4.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_policy_defaults_and_config_bounds` | M1/M3 | Defaults to 15 seconds; rejects timeout below 1 or above 120; legacy config still loads. |
| `test_read_path_issues_no_write_on_migrated_plane` | M1 | Trace SQL for `get_page`, FTS, symbols, stats, dump and hashes; assert no DML/DDL. |
| `test_write_begins_immediate_and_rolls_back` | M1 | Assert begin precedes write and failed body rolls back. |
| `test_busy_at_begin_raises_wiki_store_busy` | M1 | Hold a peer writer and assert typed error includes path, operation, and wait duration. |
| `test_migrate_is_read_first_and_latched` | M1 | Current schema causes no write; legacy plane migrates once and preserves version update. |
| `test_readonly_ladder_sets_only_read_safe_timeout` | M1 | `mode=ro` / immutable paths get timeout yet never migrate or set write pragmas. |
| `test_checkpoint_truncate_reader_fallback_is_nonfatal` | M1 | Busy truncation falls back to passive and logs rather than raising. |
| `test_source_manager_uses_timeout_and_immediate_writes` | M2 | SQLite source upsert/migration uses explicit policy; JSON/Arango branches are unchanged. |
| `test_status_contains_sqlite_block` | M4 | JSON and human output include effective settings without removing prior payload fields. |
| `test_upsert_busy_is_soft_skip` | M4 | `WikiStoreBusy` produces actionable non-error upsert output. |

### Integration Tests

| Test | Description |
|---|---|
| `test_build_and_remember_multiprocess_contention` | Marked `slow`: run a controlled writer/build-like loop and a peer remember/source write against one WAL file; all writes either complete within timeout or report typed busy, never raw `database is locked`. |
| `test_build_and_ingest_checkpoint_only_long_writers` | Verify successful build/ingest request checkpoint and `upsert --changed` does not. |
| `test_existing_wiki_suite_regression` | Run `packages/ai-parrot/tests/knowledge/wiki/` unchanged alongside the added focused tests. |

### Test Data / Fixtures

- A current-schema temporary SQLite wiki containing a page, source, and symbol rows.
- A legacy-schema temporary wiki missing migration columns and carrying an old `meta.schema_version`.
- Two independently opened processes/connections, coordinated by `multiprocessing.Event`, to hold an immediate writer
  lock deterministically.
- A live-reader fixture to block `wal_checkpoint(TRUNCATE)` without corrupting or deleting the WAL.

---

## 5. Acceptance Criteria

- [ ] Existing `BaseWikiStore` methods and their signatures remain compatible; no schema/data rewrite is introduced.
- [ ] `WikiProjectConfig` persists `sqlite_busy_timeout=15.0` by default, validates 1–120 seconds, and defaults
  `sqlite_performance_pragmas` to `False` for legacy config files.
- [ ] Every writable SQLite store path acquires `BEGIN IMMEDIATE` before DML and maps busy at that boundary to
  `WikiStoreBusy`; ordinary statement, read-only, disk, and I/O errors retain their existing semantics.
- [ ] Pure read methods on an already-migrated plane issue zero write statements, and the read-only ladder neither
  migrates nor applies write-capable pragmas.
- [ ] Required safe policy is visible: `busy_timeout`, `synchronous=NORMAL`, and 64 MiB `journal_size_limit`; mmap,
  cache, and temp-store tuning are only applied with `sqlite_performance_pragmas=True`.
- [ ] `SourceCollectionManager` SQLite writes use the same bounded explicit transaction strategy; JSON and ArangoDB
  modes remain behaviourally unchanged.
- [ ] `build` and `ingest` invoke non-fatal checkpointing under their existing writer lock; `upsert --changed` does not.
- [ ] `wikitoolkit status` reports a backward-compatible SQLite diagnostics block.
- [ ] Focused unit tests and marked slow multiprocess stress test pass, plus
  `pytest packages/ai-parrot/tests/knowledge/wiki/ -v` and `ruff check` for touched files.

---

## 6. Codebase Contract

### Verified Imports

```python
import sqlite3  # packages/ai-parrot/src/parrot/knowledge/wiki/store.py:32
from contextlib import asynccontextmanager  # packages/ai-parrot/src/parrot/knowledge/wiki/store.py:35
import aiosqlite  # packages/ai-parrot/src/parrot/knowledge/wiki/store.py:41
from parrot.knowledge.wiki.store import BaseWikiStore, SQLiteWikiStore, WikiPageRecord, create_wiki_store
# packages/ai-parrot/src/parrot/knowledge/wiki/federation.py:53
```

`aiosqlite>=0.17` is already a core dependency in `packages/ai-parrot/pyproject.toml:172`; no dependency change is
authorized or required. `sqlite3` is from the Python standard library.

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
class SQLiteWikiStore(BaseWikiStore):  # line 711
    def __init__(self, db_path: str | Path, wiki_name: str = "", *, read_only: bool = False) -> None:  # lines 744-750
    async def _connect(self) -> AsyncIterator[aiosqlite.Connection]:  # line 820
    async def _migrate(self, conn: aiosqlite.Connection) -> None:  # line 1041
    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int:  # line 1134
    async def replace_source_slice(self, source_id: str, pages: list[WikiPageRecord], edges: Optional[list[tuple[str, str, str]]] = None) -> dict[str, Any]:  # line 1176
    async def delete_page(self, concept_id: str) -> bool:  # line 1274
    async def upsert_embedding(self, concept_id: str, vector: list[float], model: str = "") -> None:  # line 1299
    async def get_page(self, concept_id: str, include_body: bool = True) -> Optional[dict[str, Any]]:  # line 1515
    async def search_fts(self, query: str, category: Optional[str] = None, limit: int = 10) -> list[dict[str, Any]]:  # line 1582
    async def neighbors(self, concept_id: str, rel: Optional[str] = None, direction: str = "both") -> list[dict[str, Any]]:  # line 1672
    async def stats(self) -> dict[str, Any]:  # line 1735

# packages/ai-parrot/src/parrot/knowledge/wiki/sources.py
class SourceCollectionManager:  # line 107
    def _connect(self) -> sqlite3.Connection:  # line 995
    def _upsert(self, entry: SourceManifestEntry) -> None:  # line 1007
    def _upsert_many(self, entries: list[SourceManifestEntry]) -> None:  # line 1019
    def _migrate_sources_columns(self) -> None:  # line 1370

# packages/ai-parrot/src/parrot/knowledge/wiki/project.py
class WikiProjectConfig(BaseModel):  # line 365
    def storage_path(self, root: Path) -> Path:  # line 472
    def db_path(self, root: Path) -> Path:  # line 477
    def is_built(self, root: Path) -> bool:  # line 481
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| Config policy | Store factory | `create_wiki_store(storage_dir, wiki_name, backend, **kwargs)` | `store.py:1795-1835` |
| CLI store resolver | SQLite factory | `_open_store()` calls `create_wiki_store`; `_open_sources()` creates the SQLite source manager | `cli.py:394-444` |
| Federation | foreign read-only store | `SQLiteWikiStore(..., read_only=True)` | `federation.py:277` |
| Toolkit | local store/source manager | `create_wiki_store(...)` and `SourceCollectionManager(..., db_path=...)` | `toolkit.py:124-149` |
| Sync/execution | local store construction | `create_wiki_store(...)` | `sync.py:97-108`, `execution.py:162-164` |
| Build diagnostics | report writer | `_write_build_stats(...)` is called after build statistics | `cli.py:1204-1227`, `cli.py:1533-1542` |
| CLI status | public payload | `read_store.stats()` is folded into `payload` | `cli.py:1961-2015` |

### Does NOT Exist (Anti-Hallucination)

- ~~`SQLitePragmaPolicy`~~ — no current policy model exists.
- ~~`WikiStoreBusy`~~ — no typed SQLite busy exception exists.
- ~~`SQLiteWikiStore._open()` / `_read()` / `_write()` / `checkpoint()` / `close()`~~ — none exists today.
- ~~`WikiProjectConfig.sqlite_busy_timeout` / `sqlite_performance_pragmas`~~ — neither exists today.
- ~~`PRAGMA busy_timeout`, `BEGIN IMMEDIATE`, `PRAGMA synchronous`, `PRAGMA journal_size_limit`, or
  `PRAGMA wal_checkpoint` under `parrot.knowledge.wiki`~~ — no implementation currently issues them.
- ~~A wiki concurrency test module~~ — `packages/ai-parrot/tests/knowledge/wiki/` has no
  `test_store_concurrency.py` today.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Keep I/O async in `SQLiteWikiStore`; use `aiosqlite`, `asynccontextmanager`, strict typing, and `self.logger`.
- Keep `SourceCollectionManager` synchronous by design, but use short-lived `sqlite3` connections with explicit
  transactions; do not block async callers directly.
- Configure both `timeout=` (SQLite busy handler installation) and `PRAGMA busy_timeout` (visible effective setting).
- Set `isolation_level=None` only where the code explicitly owns `BEGIN IMMEDIATE` / `COMMIT` / `ROLLBACK`; do not
  leave implicit transaction boundaries.
- Apply `journal_mode` / `synchronous` only on write-capable opens. Read-only `mode=ro` and immutable fallbacks may
  receive busy timeout and read-safe performance settings only.
- Test SQLite error codes, not message substrings, for codes 5 (`SQLITE_BUSY`) and 517 (`SQLITE_BUSY_SNAPSHOT`).

### Known Risks / Gotchas

- `BEGIN IMMEDIATE` solves read-to-write upgrade contention by acquiring the writer reservation before any transaction
  reads; it does not make arbitrary later statement errors a busy-timeout condition.
- A reader can prevent TRUNCATE even after writer success. Treat it as observable maintenance, fall back to PASSIVE,
  and never fail a build or ingest for it.
- `journal_size_limit` constrains retained WAL size after a successful checkpoint, not WAL growth while old reader
  snapshots remain open.
- Preserve the current read-only fallback's live-sidecar safety checks: immutable connections must never serve data
  that omits a live WAL/journal.
- Persistent writer ownership must be explicit and close safely; default remains connection-per-call.
- Do not add policy kwargs to all backends blindly: `create_wiki_store()` routes satellite backend kwargs as well.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `aiosqlite` | `>=0.17` (existing) | Existing async SQLite connection layer. |
| `sqlite3` | Python standard library | Existing synchronous source manager and SQLite error codes/pragmas. |

### Worktree Strategy

Isolation: **per-spec**. M1 is the dependency root and must land before M3/M4/M5 consume its policy/error interfaces.
After M1, M2 can proceed independently; M3 and M4 may proceed in separate worktrees once exact constructor names are
available; M5 follows the final behavior. No task may modify the ledger, `wiki_write_lock`, or unrelated backends.

---

## 8. Open Questions

- [x] Long-lived writer connection — *Owner: Jesus*: opt-in `persistent_writer`, default off; connection-per-call
  with `BEGIN IMMEDIATE` remains default.
- [x] Timeout expiry — *Owner: Jesus*: raise `WikiStoreBusy` with database path, operation, and waited seconds; MCP
  tools show actionable guidance and CLI upsert soft-skips.
- [x] Migration cache — *Owner: Jesus*: per-store `asyncio.Event` plus read-first migration probe; no process-global
  state.
- [x] Configuration surface — *Owner: Jesus*: `sqlite_busy_timeout` and `sqlite_performance_pragmas`; always use
  `synchronous=NORMAL` and 64 MiB journal limit; mmap/cache/temp-store remain opt-in.
- [x] Busy-timeout default — *Owner: Jesus*: 15 seconds, validated 1–120 seconds.
- [x] Checkpoint location — *Owner: Jesus*: after `build` and `ingest` only, never `upsert --changed`.
- [ ] Target version — *Owner: release maintainer*: this spec records `next minor`; choose the concrete release when
  scheduling. This does not block task decomposition or implementation.

---

## 9. Design Research Cross-Check

Model: `gpt-5` · Status: skipped (no independent design-review transcript was supplied or generated; the accepted
brainstorm is authoritative for this spec) · Transcript: —

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Independent review | skipped | No separate review artifact exists; do not invent one. | — |

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-14 | Jesus Lara / Codex | Formalized accepted SQLite concurrency-hardening brainstorm as FEAT-557. |
