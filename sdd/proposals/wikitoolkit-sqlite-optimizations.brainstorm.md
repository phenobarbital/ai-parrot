---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Brainstorm: wikitoolkit SQLite concurrency hardening (busy_timeout, BEGIN IMMEDIATE, read-first migrate, pragmas)

**Date**: 2026-09-14
**Author**: Jesus Lara (drafted with Claude)
**Status**: exploration
**Recommended Option**: B
**Feeds**: `sdd/proposals/sdd-work-ledger.brainstorm.md` (2026-09-13) — this is its "Lane 1: `store.py` hardening" carved out as a standalone, behaviour-preserving feature.

---

## Problem Statement

The LLM Wiki retrieval plane (`wikitoolkit`, `parrot/knowledge/wiki/`) is a single SQLite file
(`.parrot/wiki/wiki.db`) shared by every process on the host: the `wikitoolkit mcp` server held open by
each Claude Code / Codex session, the git `post-commit` hook running `wikitoolkit upsert --changed`,
one-shot CLI commands (`query`, `page`, `remember`, `status`), and the multi-minute `wikitoolkit build`.
With N SDD agents in parallel worktrees this is N+2 processes on one file.

WAL mode is on (`WIKI_SCHEMA_SQL` starts with `PRAGMA journal_mode = WAL`, replayed only at schema
creation), but nothing else about the connection layer is configured for contention:

1. **No `busy_timeout` anywhere.** `SQLiteWikiStore._connect()` calls `aiosqlite.connect(str(self._db_path))`
   with no `timeout=`, so the `sqlite3` default of 5 s applies implicitly and invisibly. The synchronous
   `SourceCollectionManager._connect()` (`sources.py:995`) calls `sqlite3.connect(str(self.db_path))` the same way.
   No `PRAGMA busy_timeout` is issued, so `wikitoolkit status` cannot show what the effective wait is.
2. **No explicit transaction control.** No `BEGIN` is issued anywhere in `wiki/`; the `sqlite3` module opens a
   *deferred* transaction before the first DML. The write lock is therefore acquired at whatever statement happens to
   be the first write, and any future code that reads then writes inside one transaction (the ledger's atomic
   `issue.claimed` check-then-update is exactly that) is exposed to `SQLITE_BUSY_SNAPSHOT`, which SQLite raises
   *without* invoking the busy handler — no timeout applies, the transaction just fails.
3. **`_migrate()` writes on every connection.** `store.py:1059-1063` runs
   `UPDATE meta SET value = ? WHERE key = 'schema_version' AND value != ?` followed by `conn.commit()` on *every*
   `_connect()`, including the read paths (`search_fts`, `get_page`, `neighbors`, `stats`, …). An `UPDATE` that
   changes zero rows still starts a write transaction, so every reader in every process competes for the single
   WAL writer lock. With N agents querying, readers stall behind `build` for no reason.
4. **`build` starves late writers.** `replace_source_slice` commits per source (milliseconds each), but a repo scan
   is hundreds of back-to-back slices. SQLite's busy handler has no fairness: a `wiki_remember` arriving mid-build
   retries with sleeps and can exhaust the implicit 5 s while the builder re-acquires the lock every time. The
   result the owner observed: an agent trying to register a finding during a rebuild gets `database is locked`.
5. **The WAL can grow unbounded.** `wal_autocheckpoint` cannot complete while any reader holds a snapshot; with
   MCP servers constantly reading, `wiki.db-wal` keeps growing across a build and nothing ever truncates it.

The advisory `wiki.lock` (`project.py:wiki_write_lock`, `flock`) is *not* the problem: it serialises `build` vs
`upsert` only (`cli.py:1394`, `cli.py:1641`); `remember`/`note`/`link` and the MCP tools never take it. Their only
contention is SQLite's, which is what this feature fixes.

**Who is affected**: every SDD agent using `wiki_remember` / `wiki_note` while another process builds; the
`post-commit` hook; the work-ledger design, which cannot promise "a ledger write never fails during a rebuild"
until this lands.

## Constraints & Requirements

- **Behaviour-preserving.** Public `BaseWikiStore` API unchanged; every existing test in
  `packages/ai-parrot/tests/knowledge/wiki/` passes unmodified. No schema change, no data rewrite.
- **Scope = store hardening only** (Round 1). `store.py`, `sources.py`, `WikiProjectConfig`, the `build`
  checkpoint and `status` reporting. No ledger file, no second lock, no `flock` rework — those belong to the
  work-ledger spec, which depends on this one.
- **Readers never take the write lock.** After the change, a pure read path (`search_fts`, `get_page`, `neighbors`,
  `stats`, `symbols_for`, `find_symbols`, `page_hashes`, `dump_*`) on an already-migrated plane must issue zero
  write statements.
- **Every write path acquires the writer lock up front** with `BEGIN IMMEDIATE`, so the wait is bounded by
  `busy_timeout` and a transaction that has started can no longer fail on contention.
- **Explicit, configurable, visible timeout.** `WikiProjectConfig.sqlite_busy_timeout` (seconds; proposed default
  15, valid range 1–120) committed in `.parrot/wiki.json`, propagated as a constructor kwarg to both
  `SQLiteWikiStore` and `SourceCollectionManager`, and shown by `wikitoolkit status`.
- **Performance pragmas opt-in** (Round 2): `synchronous=NORMAL` and `journal_size_limit` always;
  `mmap_size` / `cache_size` / `temp_store` only when `sqlite_performance_pragmas: true` — N agents × 256 MB mmap is
  not a default anyone asked for.
- **Long-lived writer is opt-in** (Round 1): default stays connection-per-call so the read-only degradation ladder in
  `_connect()` keeps its "never sticky" property; a constructor flag enables a persistent per-process writer
  connection guarded by an `asyncio.Lock` (the ledger will turn it on).
- **Typed failure** (Round 1/2): `WikiStoreBusy(sqlite3.OperationalError)` carrying `db_path`, `operation`,
  `waited_seconds`; existing `except sqlite3.OperationalError` clauses in `_connect()` keep working; MCP tools turn
  it into an actionable message; `wikitoolkit upsert` treats it as the same soft skip the `flock` timeout is.
- **The read-only ladder must keep working.** `read_only=True` stores (`federation.py:277`, `cli.py:840`) and the
  `mode=ro` / `immutable=1` fallbacks must get `busy_timeout` too (WAL readers can hit `SQLITE_BUSY` during a peer's
  checkpoint or recovery) but must never issue pragmas that write (`journal_mode`, `wal_checkpoint`) nor migrate.
- **Migration still happens** on legacy planes. `_migrate()` reads `PRAGMA table_info` + `schema_version` first and
  only issues `ALTER`/`UPDATE` when something actually differs; the "already migrated" state is cached per store
  instance (`asyncio.Event`), never globally.
- **Evidence** (Round 2): a multi-process stress test in pytest (simulated build loop in a child process + N
  concurrent `remember()` writers, zero `database is locked`, marked slow, hard timeout), a reproducible script under
  `artifacts/` driving the real `wikitoolkit build` + `wiki_remember`, and `status` printing effective pragmas.
- **No new dependency.** `aiosqlite` 0.22.1 and stdlib `sqlite3` (SQLite 3.45.1, `THREADSAFE=1`) already support
  everything: `aiosqlite.connect(database, **kwargs)` forwards `timeout=` and `isolation_level=` to `sqlite3.connect`.
- Async-first, Pydantic config, Google docstrings, `self.logger`, `black`/`ruff` gates per `.claude/rules/`.

---

## Options Explored

### Option A: Minimal patch inside `_connect()` — timeout, pragmas, read-first migrate, `BEGIN IMMEDIATE` per write method

Keep the current shape (one `_connect()` for everything, connection per call). Add `timeout=` to the three
`aiosqlite.connect` calls and the sync `sqlite3.connect`, issue `PRAGMA busy_timeout` / `synchronous=NORMAL` /
`journal_size_limit` right after opening, make `_migrate()` read before it writes, and have each of the seven write
methods (`upsert_pages`, `add_edges`, `replace_source_slice`, `delete_page`, `upsert_embedding`, `upsert_symbols`,
`rebuild_from_tree`) execute `BEGIN IMMEDIATE` as their first statement (with `isolation_level=None` on the
connection so the module stops issuing implicit `BEGIN`s). `build` ends with `PRAGMA wal_checkpoint(TRUNCATE)`.

✅ **Pros:**
- Smallest diff; every change is local to `store.py` + one line in `sources.py`.
- Fixes the four concrete defects (timeout, snapshot exposure, reader write-lock, WAL growth) directly.
- Easy to review for behaviour preservation.

❌ **Cons:**
- `BEGIN IMMEDIATE` sprinkled across seven methods is a rule enforced by discipline, not structure; the ledger
  (and any new write method) can forget it.
- `isolation_level=None` on a shared `_connect()` changes semantics for *readers* too (harmless, but the read paths
  then carry write-mode plumbing they never use).
- No place to hang the opt-in persistent writer, the typed `WikiStoreBusy`, or `status` reporting without growing
  `_connect()` further — it is already 90 lines with a three-rung fallback ladder.
- Timeout stays a constructor kwarg only unless config plumbing is added anyway.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiosqlite` 0.22.1 | async SQLite driver | already the store driver; `**kwargs` → `sqlite3.connect` |
| `sqlite3` (stdlib, SQLite 3.45.1) | sync manager + pragmas | `BEGIN IMMEDIATE`, `busy_timeout`, `wal_checkpoint` all available |

🔗 **Existing Code to Reuse:**
- `parrot/knowledge/wiki/store.py::SQLiteWikiStore._connect` (`store.py:820`) — extend in place.
- `parrot/knowledge/wiki/store.py::SQLiteWikiStore._migrate` (`store.py:1041`) — read-first rewrite.
- `parrot/knowledge/wiki/sources.py::SourceCollectionManager._connect` (`sources.py:995`) — add `timeout=`.

---

### Option B: Connection-policy split — `_read()` / `_write()` context managers, `SQLitePragmaPolicy`, opt-in persistent writer, `WikiStoreBusy`, `checkpoint()` (recommended)

Refactor the connection layer of `SQLiteWikiStore` into two explicit entry points with one shared opener:

- **`_open(conn_kwargs)`** — the existing three-rung logic (write-capable → `mode=ro` → `immutable=1`) becomes the
  single place that creates a connection and applies a **`SQLitePragmaPolicy`** (Pydantic model: `busy_timeout_s`,
  `synchronous`, `journal_size_limit_bytes`, `performance: bool` → `mmap_size`/`cache_size`/`temp_store`). Read-only
  rungs get only the read-safe subset (`busy_timeout`, cache/mmap/temp_store), never `journal_mode`/`synchronous`.
- **`_read()`** — yields a connection for SELECT-only paths. Ensures schema/migration state via a *read-first probe*
  and never executes a DML unless a migration is genuinely pending (legacy plane), in which case it hands off to the
  write path once.
- **`_write(operation: str)`** — `isolation_level=None`, applies the policy, ensures schema once per instance
  (`asyncio.Event` "migrated" latch guarded by the existing `_init_lock`), then `BEGIN IMMEDIATE` / `COMMIT` /
  `ROLLBACK` exactly as the owner's skeleton. A `sqlite3.OperationalError` whose message/`sqlite_errorcode` is
  `SQLITE_BUSY` (5) or `SQLITE_BUSY_SNAPSHOT` (517) raised **at the `BEGIN IMMEDIATE`** is re-raised as
  `WikiStoreBusy(db_path, operation, waited_seconds)`; errors after the lock is held propagate untouched.
- **Opt-in persistent writer** — `SQLiteWikiStore(..., persistent_writer=False)`. When `True`, `_write()` reuses
  one long-lived `aiosqlite.Connection` per instance behind an `asyncio.Lock` (serialises tasks in-process;
  `BEGIN IMMEDIATE` serialises across processes) and skips the per-call schema probe. `close()` becomes meaningful.
  Off by default so the read-only degradation stays per-connection and non-sticky.
- **`checkpoint(truncate: bool = True)`** — new `SQLiteWikiStore` method running `PRAGMA wal_checkpoint(TRUNCATE)`,
  falling back to `PASSIVE` when readers hold snapshots (`busy` column of the result is 1), logged at debug. Called
  at the end of `wikitoolkit build` (and `ingest`), inside the `wiki_write_lock`.
- **`SourceCollectionManager`** gets `busy_timeout` and uses `sqlite3.connect(..., timeout=, isolation_level=None)`
  with the same `BEGIN IMMEDIATE`/`COMMIT` pair in its write methods (sync mirror of `_write()`).
- **Config plumbing** — `WikiProjectConfig.sqlite_busy_timeout: float = 15.0` and
  `sqlite_performance_pragmas: bool = False`; `create_wiki_store(..., sqlite_policy=...)` forwards them; all six
  creation sites (`cli.py:412/421/541/840/2800`, `mcp_server.py:120/130`, `sync.py:99/108`, `toolkit.py:124`,
  `execution.py:162`, `federation.py:277`) pass the policy resolved from the *local* config.
- **`wikitoolkit status`** adds a `sqlite` block: `journal_mode`, `busy_timeout_ms`, `synchronous`,
  `journal_size_limit`, `wal_bytes` (size of `wiki.db-wal`), `persistent_writer`.
- **Evidence**: `tests/knowledge/wiki/test_store_concurrency.py` (multiprocess stress, `@pytest.mark.slow`, joins
  children, hard 120 s timeout) + `artifacts/wiki_sqlite_stress/run.sh` producing a log under `artifacts/logs/`.

✅ **Pros:**
- The rule "writes start with `BEGIN IMMEDIATE`, readers never write" is structural: a new write method that uses
  `_read()` cannot commit, and one that uses `_write()` cannot forget the lock.
- One pragma policy object is what `status` prints, what tests assert, and what the ledger will pass — no drift.
- `WikiStoreBusy` gives MCP tools and the CLI a precise signal at the exact point contention is detected, while
  remaining an `OperationalError` for every existing `except`.
- Persistent writer is available for the ledger without forcing it on the wiki plane.
- `checkpoint()` bounds WAL growth where it belongs (end of the only long writer), not as a loose pragma in `cli.py`.

❌ **Cons:**
- Larger diff in `store.py` (the connection ladder moves) — needs a careful review that each of the ~21 `_connect()`
  callers is classified read vs write correctly.
- Two code paths to keep consistent (async store, sync manager) — mitigated by sharing the policy model and pragma
  SQL constants.
- Persistent writer introduces a real `close()` lifecycle that the MCP server and toolkit must call on shutdown.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiosqlite` 0.22.1 | async driver | `connect(path, timeout=…, isolation_level=None)` |
| `sqlite3` stdlib / SQLite 3.45.1 | sync manager, pragmas, `wal_checkpoint` | `sqlite_errorcode` attribute (3.11+) for 5 / 517 classification |
| `pydantic` v2 | `SQLitePragmaPolicy`, config fields | already used by `WikiProjectConfig` |
| `pytest` + `multiprocessing` | stress test | no new dep; mark `slow`, wrap with `timeout -s KILL` in CI per repo memory |

🔗 **Existing Code to Reuse:**
- `store.py:820-908` `_connect()` — the fallback ladder becomes `_open()`; `_connect_readonly` (`store.py:951`) and
  `_connect_immutable` (`store.py:933`) become read-only rungs that receive the read-safe pragma subset.
- `store.py:793` `self._init_lock = asyncio.Lock()` — guards the new migrated-latch.
- `store.py:1041` `_migrate()` — read-first rewrite; `_MIGRATION_COLUMNS` (`store.py:166`) and `_SCHEMA_TABLES`
  (`store.py:176`) unchanged.
- `store.py:749-756` `_READONLY_ENV_CODES` / `_is_readonly_env_error` — pattern to mirror for a `_is_busy_error`.
- `sources.py:995` `SourceCollectionManager._connect()` and its write methods (`_upsert`, `_migrate_*`).
- `project.py:365` `WikiProjectConfig` — new fields; `project.py:65` `wiki_write_lock` untouched.
- `cli.py:1394` `build` (checkpoint at end, inside the lock), `cli.py:1641` `upsert` (busy → skip),
  `cli.py:1961` `status` (pragma block).
- `tools.py:272` `WikiRememberTool` / `WikiNoteTool` `_execute` — catch `WikiStoreBusy`, return actionable text.

---

### Option C: Single-writer broker — all writes funnel through the resident `wikitoolkit mcp` process

Stop having multiple writer processes at all. The long-running MCP server (one per session, but electable to one
per store via a lock file) owns the only writer connection; `build`, `upsert` and one-shot `remember` become clients
that submit their work over a Unix socket (or by appending to a spool directory the broker drains). SQLite then has
exactly one writer, contention disappears, and `BEGIN IMMEDIATE` becomes irrelevant.

✅ **Pros:**
- Eliminates cross-process write contention by construction; SQLite runs single-writer, its happiest mode.
- Natural home for write batching and for the ledger's append log.

❌ **Cons:**
- A daemon with election, liveness and crash-recovery semantics is a new subsystem; `build` (hundreds of MB of page
  bodies) over a socket is slow and memory-heavy.
- The post-commit hook and one-shot CLI must work when *no* MCP server is running — so the per-process writer path
  has to exist anyway, and needs exactly the hardening in Options A/B.
- Violates "no new heavy machinery" and the behaviour-preserving constraint; unrelated to the four concrete defects.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `asyncio` Unix sockets (stdlib) | broker IPC | no dep; protocol + framing to design |
| `aiosqlite` | broker's single writer | unchanged |

🔗 **Existing Code to Reuse:**
- `mcp_server.py:110-140` — store lifecycle, would host the broker.
- `project.py:65` `wiki_write_lock` — could become the broker election lock.

---

### Option D (unconventional): Shadow build — `build` writes `wiki.db.next` and atomically swaps, so the long writer never touches the live file

Instead of making the live file tolerate a multi-minute writer, remove the writer: `build` renders into a fresh
sibling database and, inside `wiki_write_lock`, replaces `wiki.db` (`os.replace`) at the end. Concurrent
`remember`/`upsert` writes continue against the live file with a short timeout, and are *replayed* onto the new file
from an operations journal before the swap.

✅ **Pros:**
- Live file sees only millisecond writers; readers never wait on `build`.
- Build becomes crash-safe (partial build never corrupts the live plane).

❌ **Cons:**
- Swapping a WAL database under open connections is unsafe: the `-wal`/`-shm` sidecars are bound to the file name,
  and a peer with an open connection sees the old inode until it reconnects — exactly the "immutable staleness
  window" `_connect_readonly` already documents. Connection-per-call mitigates but does not eliminate it.
- Requires an operations journal for writes that land during the build (the work-ledger's `events.jsonl` idea, but
  for the wiki plane itself) — scope creep well beyond hardening.
- Does nothing for the readers-take-write-lock and no-timeout defects; those are needed regardless.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `os.replace` (stdlib) | atomic swap | POSIX rename semantics only |
| `aiosqlite` | build into shadow file | unchanged |

🔗 **Existing Code to Reuse:**
- `cli.py:1394` `build` under `wiki_write_lock`.
- `store.py:910` `_sidecars_quiescent` — the same sidecar reasoning that makes the swap risky.

---

## Recommendation

**Option B** is recommended because:

- It fixes all five problems with one coherent mechanism instead of five point patches, and it makes the two
  invariants that matter — *readers never write*, *writers lock first* — properties of the code's shape rather than
  of reviewer vigilance. Option A fixes the same defects today but leaves the ledger (the very next consumer, whose
  `issue.claimed` is a read-then-write transaction) free to reintroduce the `SQLITE_BUSY_SNAPSHOT` exposure.
- Every Round 1/2 decision maps onto a named piece of B: `WikiStoreBusy` at the `BEGIN IMMEDIATE` boundary,
  opt-in `persistent_writer`, per-instance migrated latch with read-first probe, `wiki.json` + kwarg config with
  performance pragmas opt-in, `checkpoint()` as a store method, `status` visibility, and the stress test.
- Options C and D solve contention by moving the writer somewhere else, but both still need B's hardening for the
  no-daemon / live-file paths, so they are additive later designs, not alternatives now.

What we trade: a medium-sized refactor of `store.py`'s connection layer and the need to classify ~21 call sites as
read or write. That classification is mechanical (the seven write methods are already listed in the `BaseWikiStore`
ABC; everything else is a read), and the existing wiki test suite plus the new stress test verify preservation.

Honest note on the snapshot claim: with the `sqlite3` module's default `isolation_level`, the implicit `BEGIN` is
issued immediately before the first DML, so today's `replace_source_slice` runs its preliminary `SELECT`s in
autocommit and is *not* currently exposed to `SQLITE_BUSY_SNAPSHOT`. The exposure is a latent one for any
transaction that reads then writes — which the ledger requires. `BEGIN IMMEDIATE` is still the right change: it
moves the lock wait to a single, busy-handler-governed point and is what lets `WikiStoreBusy` be raised precisely.

---

## Feature Description

### User-Facing Behavior

- `wikitoolkit build` running in one terminal no longer makes `wiki_remember` / `wiki_note` / `wiki_link` from an
  agent session fail with `database is locked`. The write waits up to `sqlite_busy_timeout` (default 15 s) for the
  builder's current slice to commit (milliseconds), then proceeds.
- If the wait is exhausted anyway, the MCP tool returns an actionable message, e.g.
  `wiki store busy after 15.0s (wikitoolkit build in progress?) — retry, or raise sqlite_busy_timeout in .parrot/wiki.json`,
  instead of a raw traceback. `wikitoolkit upsert` (post-commit hook) prints the same soft "skipping — the build
  will cover these files" it prints on a `flock` miss, and exits 0.
- `wikitoolkit status` gains a `sqlite` section showing `journal_mode`, `busy_timeout_ms`, `synchronous`,
  `journal_size_limit`, the current `-wal` size, and whether the performance pragmas / persistent writer are on.
- `.parrot/wiki.json` accepts two new optional keys: `sqlite_busy_timeout` (seconds) and
  `sqlite_performance_pragmas` (bool). Existing files without them keep working with the defaults.
- After `build` (and `ingest`) the `wiki.db-wal` file is truncated back to near zero instead of carrying the whole
  build's history.
- Read-only queries (`query`, `page`, `related`, `symbols …`) are unaffected in output and get slightly faster on a
  busy host because they no longer queue behind writers.

### Internal Behavior

1. **Policy resolution.** `load_project_config` yields a `WikiProjectConfig` whose two new fields are folded into a
   `SQLitePragmaPolicy`. `create_wiki_store(..., backend="sqlite")` accepts the policy (kwarg) and passes it to
   `SQLiteWikiStore`; `SourceCollectionManager` accepts `busy_timeout`. Call sites without a config (e.g.
   `execution.py`) fall back to the policy's defaults.
2. **Opening.** A single opener applies the policy to every new connection: `timeout=` on
   `aiosqlite.connect`/`sqlite3.connect` (installs the busy handler), then `PRAGMA busy_timeout`, and on
   write-capable connections `PRAGMA synchronous = NORMAL` and `PRAGMA journal_size_limit`. Performance pragmas
   (`mmap_size`, `cache_size`, `temp_store`) are applied on both read and write connections only when enabled.
   Read-only rungs (`mode=ro`, `immutable=1`) receive only the read-safe subset.
3. **Schema / migration state.** The first connection of a store instance runs the presence probe; if tables are
   missing, the schema is replayed (existing behaviour). Then `_migrate()` runs *read-first*: `PRAGMA table_info`
   per table and a `SELECT value FROM meta WHERE key='schema_version'`; only if a column is missing or the version
   differs does it open a write transaction (`BEGIN IMMEDIATE`, `ALTER`/`UPDATE`, `COMMIT`). Success sets the
   per-instance `asyncio.Event`; subsequent connections skip the probe entirely. A schema-missing probe result on a
   later connection (externally replaced plane) clears the latch and re-runs.
4. **Reads.** `_read()` yields a connection with no transaction control; callers issue SELECTs and exit. No commit,
   no DML, ever.
5. **Writes.** `_write(operation)` opens (or, with `persistent_writer=True`, reuses under the `asyncio.Lock`) a
   connection with `isolation_level=None`, executes `BEGIN IMMEDIATE`, yields, then `COMMIT`; on any exception
   `ROLLBACK` and re-raise. A busy error at `BEGIN IMMEDIATE` becomes `WikiStoreBusy` with the operation name and
   the configured wait. The seven write methods use `_write()`; `replace_source_slice` keeps its per-source
   granularity so the lock window stays at one slice, and `build` sleeps a few milliseconds after each slice commit
   (politeness pause) so concurrent writers are not starved by back-to-back lock re-acquisition.
6. **Checkpoint.** `checkpoint(truncate=True)` runs `PRAGMA wal_checkpoint(TRUNCATE)` through `_write`-less
   autocommit (checkpoints are not transactional) and inspects the `busy` column; if readers block truncation it
   logs and retries once as `PASSIVE`. `build` calls it after `_write_build_stats`, still inside `wiki_write_lock`.
7. **Sync manager.** `SourceCollectionManager` mirrors 2 and 5 with the stdlib `sqlite3` connection (`timeout=`,
   `isolation_level=None`, explicit `BEGIN IMMEDIATE`/`COMMIT`), raising the same `WikiStoreBusy`.
8. **Reporting.** `status` opens a read connection and prints the pragma values it actually observes, plus the
   `-wal` file size, so field diagnosis does not depend on trusting the config.

### Edge Cases & Error Handling

- **Timeout exhausted at `BEGIN IMMEDIATE`** → `WikiStoreBusy`. MCP tools: message + suggestion; CLI `upsert`:
  soft skip, exit 0; CLI `remember`/`note`/`link`: message, exit 1; `build`: cannot happen for the lock (it holds
  `wiki.lock`) but can for a straggling MCP writer — propagate with the slice's `source_id` in the log.
- **Error after the lock is held** (constraint violation, disk full, I/O) → `ROLLBACK`, propagate untouched; not
  wrapped as busy.
- **Read-only environment** (the existing `_READONLY_ENV_CODES` ladder) → unchanged classification; the ladder is
  evaluated on the write-capable open *before* `BEGIN IMMEDIATE`, so a read-only plane degrades to `mode=ro` exactly
  as today and a write on it still raises `PermissionError` via `_assert_writable` for `read_only=True` stores or
  `sqlite3.OperationalError: attempt to write a readonly database` otherwise.
- **Legacy plane (schema v1, missing columns) opened by a reader first** → the read-first probe detects the gap and
  performs the migration once under `BEGIN IMMEDIATE`; if that hits busy (a build is running on a plane it is
  itself migrating) the reader raises `WikiStoreBusy` rather than reading with missing columns.
- **Externally replaced `wiki.db`** (e.g. restored from backup while an MCP server is alive) → the presence probe on
  the next connection sees missing tables (or a different `schema_version`) and clears the migrated latch.
- **Persistent writer connection dies** (`sqlite3.ProgrammingError: Cannot operate on a closed database`,
  `SQLITE_IOERR`) → drop it, log, reopen on next `_write()`; the `asyncio.Lock` guarantees no two tasks race the
  reopen.
- **`wal_checkpoint(TRUNCATE)` blocked by readers** → `busy=1` in the result; fall back to `PASSIVE`, log at info
  with the remaining WAL size. Never raise from `checkpoint()`.
- **`journal_size_limit` on a plane whose WAL is already larger** → takes effect at the next successful checkpoint;
  `status` shows the current size so operators can see it shrink.
- **Non-POSIX platform / `fcntl` missing** → unaffected; this feature does not touch `wiki_write_lock`.
- **Two stores on the same file in one process** (federation local + generation store) → each has its own latch and
  policy; harmless duplication of the read-first probe.
- **`sqlite_busy_timeout` set to 0 or negative in `wiki.json`** → Pydantic `ge=1` rejects at load with the field name.
- **Writer starvation under a tight build loop** → SQLite has no fairness, so `build` yields a few milliseconds
  after every slice commit (politeness pause) in addition to the longer bounded wait; a waiter's busy handler then
  gets a real window to acquire the lock.

---

## Capabilities

### New Capabilities
- `wiki-store-sqlite-concurrency`: explicit `busy_timeout` + pragma policy, `BEGIN IMMEDIATE` write transactions,
  read-first `_migrate` with per-instance latch, `WikiStoreBusy`, opt-in persistent writer, `checkpoint()`,
  `status` pragma reporting, multi-process stress evidence — for `SQLiteWikiStore` and `SourceCollectionManager`.

### Modified Capabilities
- None formally. The FEAT-498 structural-plane spec (`symbols`/`symbols_fts`, `content_hash`) touched `store.py`
  and is complete; its `_migrate` version-bump logic is preserved, only made read-first.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/knowledge/wiki/store.py` (`SQLiteWikiStore`) | modifies | connection layer split `_open`/`_read`/`_write`; `_migrate` read-first + latch; `WikiStoreBusy`; `checkpoint()`; `persistent_writer` flag; `SQLitePragmaPolicy` |
| `parrot/knowledge/wiki/sources.py` (`SourceCollectionManager`) | modifies | `busy_timeout` kwarg; `timeout=`/`isolation_level=None`; `BEGIN IMMEDIATE` in write methods |
| `parrot/knowledge/wiki/project.py` (`WikiProjectConfig`) | extends | `sqlite_busy_timeout: float = 15.0 (ge=1, le=120)`, `sqlite_performance_pragmas: bool = False`; `wiki_write_lock` untouched |
| `parrot/knowledge/wiki/store.py::create_wiki_store` | extends | forwards `sqlite_policy` kwarg for `backend="sqlite"` |
| `parrot/knowledge/wiki/cli.py` | modifies | `build`/`ingest` call `store.checkpoint()`; `upsert` treats `WikiStoreBusy` as soft skip; `status` prints `sqlite` block; store resolvers pass the policy |
| `parrot/knowledge/wiki/mcp_server.py`, `tools.py` | modifies | pass policy on store creation; `WikiRememberTool`/`WikiNoteTool`/link tool map `WikiStoreBusy` to an actionable `ToolResult` |
| `parrot/knowledge/wiki/sync.py`, `toolkit.py`, `execution.py`, `federation.py` | modifies (plumbing) | pass the policy / defaults where a `SQLiteWikiStore` is created; `federation.py:277` read-only store gets `busy_timeout` only |
| `packages/ai-parrot/tests/knowledge/wiki/` | extends | `test_store_concurrency.py` (multiprocess stress, slow), unit tests for `_write` rollback, read-first migrate, `WikiStoreBusy`, `checkpoint`, `status` block |
| `artifacts/wiki_sqlite_stress/` + `artifacts/logs/` | adds | reproducible real-CLI scenario (build in background + `wiki_remember`) with saved log |
| `sdd/proposals/sdd-work-ledger.brainstorm.md` | depends on | Lane 1 of that design is satisfied by this feature; its `ledger.db` store will pass `persistent_writer=True` |
| `docs/` (wiki usage / config reference) | extends | document the two `wiki.json` keys and the `status` block |

Breaking changes: none. New dependencies: none. Deployment: none (local files).

---

## Code Context

### User-Provided Code

```python
# Source: user-provided (owner's skeleton for the write path, to fit the current _connect())
@asynccontextmanager
async def _write(self):
    async with aiosqlite.connect(self._db_path, timeout=self._busy_timeout,
                                 isolation_level=None) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA busy_timeout = %d" % int(self._busy_timeout * 1000))
        await conn.execute("PRAGMA synchronous = NORMAL")
        await self._ensure_schema(conn)          # una vez por proceso
        await conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            await conn.execute("COMMIT")
        except BaseException:
            await conn.execute("ROLLBACK")
            raise
```

User-provided pragma table (owner):

| Pragma | Value | Why |
|---|---|---|
| `synchronous` | `NORMAL` | recommended with WAL: no corruption, only the last transactions can be lost on power cut |
| `busy_timeout` | 10000–30000 ms | redundant with `timeout=` but explicit and visible in `status` |
| `wal_autocheckpoint` / `journal_size_limit` | default / 64 MB | readers can starve the checkpoint; `build` should end with `PRAGMA wal_checkpoint(TRUNCATE)` |
| `temp_store` / `cache_size` / `mmap_size` | `MEMORY` / `-64000` / 256 MB | pure performance, optional; helps FTS |

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot/src/parrot/knowledge/wiki/store.py
WIKI_SCHEMA_SQL = """PRAGMA journal_mode = WAL; CREATE TABLE IF NOT EXISTS meta (...) ..."""   # line 53-54
_MIGRATION_COLUMNS: dict[str, list[tuple[str, str]]] = {"pages": [("origin", ...), ("asserted_by", ...), ("content_hash", ...)]}  # line 166
_SCHEMA_TABLES = frozenset({"meta", "sources", "pages", "edges", "pages_fts", "embeddings", "symbols", "symbols_fts"})  # line 176

class BaseWikiStore(ABC):                                              # line ~420
    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int: ...          # line 434
    async def add_edges(self, edges: list[tuple]) -> int: ...                       # line 437
    async def replace_source_slice(self, source_id: str, pages: list[WikiPageRecord], edges: Optional[list[tuple[str, str, str]]] = None) -> dict[str, Any]: ...  # line 440
    async def delete_page(self, concept_id: str) -> bool: ...                       # line 448
    async def upsert_embedding(self, concept_id: str, vector: list[float], model: str = "") -> None: ...  # line 451
    async def get_page(self, concept_id: str, include_body: bool = True) -> Optional[dict[str, Any]]: ...  # line 455
    async def search_fts(self, query: str, category: Optional[str] = None, limit: int = 10) -> list[dict[str, Any]]: ...  # line 466
    async def stats(self) -> dict[str, Any]: ...                                    # line 486
    async def rebuild_from_tree(...)                                                # line 508
    async def upsert_symbols(...)                                                   # line 577

class SQLiteWikiStore(BaseWikiStore):                                  # line 711
    _READONLY_ENV_CODES = frozenset({8, 264, 1544, 14})               # line 749
    @classmethod
    def _is_readonly_env_error(cls, exc: sqlite3.OperationalError) -> bool  # line 751
    def __init__(self, db_path: str | Path, wiki_name: str = "", *, read_only: bool = False) -> None  # line 759
        self._db_path: Path; self._read_only: bool; self._wiki_name: str
        self._warned_read_only = False; self._init_lock = asyncio.Lock(); self.logger  # lines 765-794
    @property db_path -> Path (797); @property read_only -> bool (802)
    def _assert_writable(self) -> None                                 # line 806  (raises PermissionError)
    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[aiosqlite.Connection]    # line 820  — aiosqlite.connect(str(self._db_path)) with NO timeout (875); presence probe; schema replay under _init_lock (885); await self._migrate(conn) on EVERY connection (900); read-only fallback on _is_readonly_env_error (904-908)
    def _sidecars_quiescent(self) -> bool                              # line 910
    @asynccontextmanager async def _connect_immutable(self)            # line 933  — "?mode=ro&immutable=1", uri=True (943)
    @asynccontextmanager async def _connect_readonly(self)             # line 951  — "?mode=ro" (978) then immutable fallback (1013)
    def _log_read_only_once(self) -> None                              # line 1025
    async def _migrate(self, conn: aiosqlite.Connection) -> None       # line 1041 — PRAGMA table_info + ALTER (1049-1053); UNCONDITIONAL "UPDATE meta SET value = ? WHERE key = 'schema_version' AND value != ?" (1059-1062); await conn.commit() (1063)
    async def _upsert_pages_conn(self, conn, pages) -> None            # line 1065
    async def _insert_edges_conn(self, conn, edges) -> None            # line 1113
    # write methods (all: self._assert_writable(); async with self._connect() as conn: ...; await conn.commit())
    async def upsert_pages(...)            # 1134
    async def add_edges(...)               # 1154
    async def replace_source_slice(...)    # 1176  — commits per source (1263)
    async def delete_page(...)             # 1274
    async def upsert_embedding(...)        # 1299
    async def upsert_symbols(...)          # 1323
    # read methods (async with self._connect() as conn: SELECT ...)
    symbols_for 1400, find_symbols 1416, search_symbols_fts 1466, page_hashes 1487, get_page 1515, list_pages 1544,
    search_fts 1582, search_vector 1630, neighbors 1672, dump_pages 1715, dump_edges 1729, stats 1735,
    orphan_sources 1763, broken_edges 1773, missing_bodies 1783

def create_wiki_store(storage_dir: str | Path, wiki_name: str = "", backend: str = "sqlite", **kwargs: Any) -> BaseWikiStore  # line 1795
    # backend == "sqlite": return SQLiteWikiStore(storage_dir / "wiki.db", wiki_name=wiki_name)   # line 1834 (kwargs NOT forwarded today)
def register_wiki_backend(name: str, factory: Callable[..., BaseWikiStore]) -> None   # line 401
```

```python
# From packages/ai-parrot/src/parrot/knowledge/wiki/sources.py
class SourceCollectionManager:                                          # line 107
    def __init__(self, sources_dir: Path, db_path: Path | None = None,
                 backend: Literal["sqlite", "json", "arangodb"] = "sqlite",
                 arango_db: Any | None = None, arango_store: Any | None = None) -> None   # line 143
    # sqlite init: with self._connect() as conn: conn.executescript(WIKI_SCHEMA_SQL); self._migrate_sources_columns(); self._migrate_json_manifest()   # lines 213-217
    def _connect(self) -> sqlite3.Connection                            # line 995 — sqlite3.connect(str(self.db_path)); row_factory = sqlite3.Row; NO timeout, NO isolation_level
    def _migrate_sources_columns(self) -> None                          # line 1370 (PRAGMA table_info guarded)
    def _migrate_json_manifest(self) -> None                            # line 1393
    # ~13 `with self._connect() as conn:` sites: 214, 328, 368, 506, 524, 793, 833, 870, 909, 1016, 1039, 1156
```

```python
# From packages/ai-parrot/src/parrot/knowledge/wiki/project.py
LOCK_FILENAME = "wiki.lock"                                             # line 40
@contextmanager
def wiki_write_lock(store_dir: Path, timeout: float = 0.0) -> Iterator[bool]   # line 65 — flock(LOCK_EX|LOCK_NB) on <store_dir>/wiki.lock, advisory, poll until deadline
class WikiProjectConfig(BaseModel):                                     # line 365
    wiki_name: str = "codebase"; storage_dir: str = ".parrot/wiki"; backend: Literal["sqlite","memory","arangodb"] = "sqlite"   # 398-400
    body_max_chars: int = Field(default=16_000, ge=1_000); max_file_kb: int = Field(default=512, ge=1)   # 403-404
    def is_built(self, root: Path) -> bool                              # line 481
    def storage_path(self, root: Path) -> Path                          # (used by cli.py:1394, 1641, mcp_server.py:117)
```

```python
# From packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
UPSERT_LOCK_WAIT_SECONDS = 3.0                                          # line 109
# build: with wiki_write_lock(config.storage_path(root)) as _acquired: ... refuses when False   # line 1394-1401
#        ... await store.upsert_pages(enriched_scan.dir_records); await store.add_edges(enriched_scan.dir_edges); counts["stats"] = await store.stats()   # ~1600s
#        _write_build_stats(...)                                         # end of build — checkpoint goes after this, inside the lock
# upsert: with wiki_write_lock(config.storage_path(root), timeout=UPSERT_LOCK_WAIT_SECONDS) as _acquired: if not _acquired: click.echo("Another wiki writer is in progress ... skipping"); return   # line 1641-1649
def status(path_: str | None, ns_opt: str | None, as_json: bool) -> None   # line 1961 — stats = _run(read_store.stats()); payload {"wiki_name","backend","stats",...}; JSON or text
# store creation sites: 412, 421, 541, 840 (SQLiteWikiStore(gen_dir / "wiki.db", read_only=True)), 2800
```

```python
# From packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py
store = create_wiki_store(storage, wiki_name=config.wiki_name, backend=config.backend)   # line 130 (sqlite/memory); arangodb branch line 120
# From packages/ai-parrot/src/parrot/knowledge/wiki/tools.py
class WikiRememberTool(AbstractTool): name = "wiki_remember"            # line 272-276; async def _execute(...) line 288
# WikiNoteTool._execute(self, page_id: str, text: str) -> ToolResult    # line 366
# From packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py — remember() line 882 → self._store.upsert_pages([record]) 926; add_edges 928
# From packages/ai-parrot/src/parrot/knowledge/wiki/federation.py — SQLiteWikiStore(storage_dir / "wiki.db", wiki_name=wiki_name, read_only=True)  line 277
# From packages/ai-parrot/src/parrot/knowledge/wiki/sync.py — create_wiki_store(storage, wiki_name=config.wiki_name, backend=config.backend)  line 108
# From packages/ai-parrot/src/parrot/knowledge/wiki/execution.py — create_wiki_store(self.storage_dir, wiki_name=f"crew:{crew_name}")  line 162
```

#### Verified Imports
```python
# These imports have been confirmed to resolve (lazy __getattr__ map in parrot/knowledge/wiki/__init__.py:65-80):
from parrot.knowledge.wiki.store import SQLiteWikiStore, BaseWikiStore, WikiPageRecord, create_wiki_store, register_wiki_backend, WIKI_SCHEMA_SQL
from parrot.knowledge.wiki.project import WikiProjectConfig, wiki_write_lock, find_project_root, load_project_config
from parrot.knowledge.wiki.sources import SourceCollectionManager
from parrot.knowledge.wiki.federation import FederatedWikiStore, open_namespace_store
import aiosqlite   # 0.22.1 — connect(database: str | Path, *, iter_chunk_size=64, loop=None, **kwargs) -> Connection; kwargs → sqlite3.connect (timeout=, isolation_level=, uri=)
import sqlite3     # SQLite 3.45.1, threadsafety=3, THREADSAFE=1; OperationalError.sqlite_errorcode available (Python 3.11+)
```

#### Key Attributes & Constants
- `SQLiteWikiStore._init_lock` → `asyncio.Lock` (store.py:793) — reuse to guard the new migrated latch.
- `SQLiteWikiStore._READONLY_ENV_CODES` → `frozenset[int]` (store.py:749) — pattern for a `_BUSY_CODES = {5, 517}` (SQLITE_BUSY, SQLITE_BUSY_SNAPSHOT).
- `_SCHEMA_TABLES` (store.py:176), `_MIGRATION_COLUMNS` (store.py:166), `SCHEMA_VERSION` (module constant used at store.py:894/1061).
- `UPSERT_LOCK_WAIT_SECONDS = 3.0` (cli.py:109) — the soft-skip precedent for `upsert`.
- `WikiProjectConfig.storage_path(root)` — the directory holding `wiki.db`, `wiki.lock`, and the `-wal`/`-shm` sidecars.
- Test suite location: `packages/ai-parrot/tests/knowledge/wiki/` (files: `test_wiki_tools.py` — references `_migrate`; `test_extra_backends.py`, `test_vault_scan.py` — use `SQLiteWikiStore`; `conftest.py`, `fixtures/`). No concurrency test exists.
- Repo memory hazard: `pytest tests/unit` can hang after the summary — the stress test must join/kill children and the CI command should wrap with `timeout -s KILL`.

### Does NOT Exist (Anti-Hallucination)
- ~~`PRAGMA busy_timeout`, `PRAGMA synchronous`, `PRAGMA journal_size_limit`, `PRAGMA wal_checkpoint`, `BEGIN IMMEDIATE`, `isolation_level`~~ — none appear anywhere under `parrot/knowledge/wiki/`; the only pragma is `journal_mode = WAL` in `WIKI_SCHEMA_SQL` (plus `PRAGMA table_info` probes).
- ~~`WikiStoreBusy`~~, ~~`SQLitePragmaPolicy`~~, ~~`SQLiteWikiStore.checkpoint()`~~, ~~`SQLiteWikiStore._read()` / `_write()` / `_open()`~~, ~~`persistent_writer`~~ — to be created.
- ~~`WikiProjectConfig.sqlite_busy_timeout`~~, ~~`WikiProjectConfig.sqlite_performance_pragmas`~~ — to be added.
- ~~`parrot/knowledge/wiki/errors.py`~~ — no errors module exists in the wiki package.
- ~~`aiosqlite.connect(..., timeout=...)` being passed today~~ — all three `aiosqlite.connect` calls (store.py:875, 943, 978) and the sync `sqlite3.connect` (sources.py:1003) pass no timeout.
- ~~`create_wiki_store(**kwargs)` forwarding kwargs to `SQLiteWikiStore`~~ — kwargs are consumed only by the `arangodb`/`postgres` branches (store.py:1834 ignores them for sqlite).
- ~~A `ledger.db`, `events.jsonl`, or ledger lock file~~ — designed in `sdd-work-ledger.brainstorm.md`, not implemented; out of scope here.
- ~~`wiki_write_lock` being taken by `remember`/`note`/`link` or by the MCP tools~~ — only `build` (cli.py:1394), `upsert` (cli.py:1641) and the global registry writer (cli.py:2261) take it.
- ~~`SQLiteWikiStore.initialize()` / `SQLiteWikiStore.close()`~~ — neither exists; `initialize()` is defined only on `ArangoDBWikiStore` (arango_store.py:258) and `build` calls it behind `if config.backend == "arangodb":` (cli.py:1451-1453, 1703). A persistent-writer lifecycle needs a new `close()` (and its MCP-server/toolkit shutdown call sites).

---

## Parallelism Assessment

- **Internal parallelism**: limited. `store.py`'s connection layer is the hub every other change depends on
  (config plumbing needs the policy type; `status`/`checkpoint`/tool error mapping need `WikiStoreBusy` and
  `checkpoint()`; the stress test needs the final write path). After the store task lands, three small lanes are
  independent: (a) `sources.py` sync mirror, (b) CLI `build`/`upsert`/`status` + MCP/tool error mapping + call-site
  plumbing, (c) stress test + `artifacts/` script. They touch disjoint files.
- **Cross-feature independence**: `sdd-work-ledger` (brainstorm, not yet spec'd) *depends on* this feature and will
  touch `store.py` again only to instantiate a second store with `persistent_writer=True`; it must not start its
  store work until this merges. No in-flight spec in `sdd/tasks/index/` currently modifies `store.py`,
  `sources.py` or `project.py` (FEAT-498 structural plane is complete). `cli.py` is shared with many features but
  the three touched commands (`build`, `upsert`, `status`) are stable.
- **Recommended isolation**: `per-spec` — one worktree, sequential tasks.
- **Rationale**: the feature is small (estimated 6–8 tasks) and every lane consumes the same new store surface; the
  cost of a hub-and-spoke worktree split exceeds the parallel gain, and a single worktree keeps the
  "behaviour-preserving" review a single diff against `store.py`.

---

## Open Questions

- [x] Flow type / base branch — *Owner: Jesus*: `feature` / `dev` (Round 0).
- [x] Scope boundary vs. `sdd-work-ledger` — *Owner: Jesus*: store hardening only; no ledger file, no second lock, no `flock` rework; the ledger consumes this as a dependency.
- [x] Long-lived writer connection — *Owner: Jesus*: opt-in constructor flag (`persistent_writer`), default off; connection-per-call + `BEGIN IMMEDIATE` remains the default so the read-only ladder stays non-sticky.
- [x] Behaviour when `busy_timeout` expires — *Owner: Jesus*: raise a typed `WikiStoreBusy` (subclass of `sqlite3.OperationalError`) with `db_path`, `operation`, `waited_seconds`; MCP tools map it to an actionable message; `upsert` CLI treats it as the same soft skip as a `flock` miss.
- [x] Migrated-state cache granularity — *Owner: Jesus*: per store instance (`asyncio.Event`) plus read-first probe in `_migrate()`; no process-global cache.
- [x] Config surface — *Owner: Jesus*: `WikiProjectConfig.sqlite_busy_timeout` + `sqlite_performance_pragmas` in `.parrot/wiki.json`, propagated as constructor kwargs; `synchronous=NORMAL` + `journal_size_limit` always, mmap/cache/temp_store opt-in.
- [x] Acceptance evidence — *Owner: Jesus*: multiprocess pytest stress test (slow, timed), reproducible `artifacts/` script with saved log, `wikitoolkit status` showing effective pragmas. `checkpoint()` as a store method was not selected as *evidence* but is part of the design (Option B).
- [x] Default value of `sqlite_busy_timeout` — *Owner: Jesus*: 15 s (`sqlite_busy_timeout: float = 15.0`, `ge=1`, `le=120`).
- [x] Build politeness pause after each `replace_source_slice` commit — *Owner: Jesus*: yes. `build` yields a few milliseconds (constant, e.g. 5 ms, `asyncio.sleep`) after every slice commit so a waiting writer's busy handler can win the lock; cost is well under a second per build.
- [x] `journal_size_limit` default — *Owner: Jesus*: 64 MB (`67108864`). Rationale (2026-09-14 measurement: `wiki.db` 578 MB, live WAL 8.9 MB, 4 KiB pages, `wal_autocheckpoint` 1000 pages ≈ 4 MB): the pragma does not cap WAL growth during a build — the WAL grows as far as open reader snapshots force it — it only sets how large the file is left after a checkpoint resets it. With `checkpoint(TRUNCATE)` at the end of `build`/`ingest` the WAL returns to 0 anyway, and between builds the 4 MB autocheckpoint keeps it small, so the limit only matters when a non-truncating checkpoint completes after a large build. 128 MB would just retain twice the disk for a marginal saving in file-growth syscalls on the next build; 64 MB (~11 % of the plane) is the right default and stays a constant, not a config field.
- [x] `SourceCollectionManager` write methods raise `WikiStoreBusy` too — *Owner: Jesus*: yes, same exception class from both the async store and the sync manager; the `asyncio.to_thread` bridge propagates it unchanged.
- [x] Federated namespaces' read-only stores — *Owner: Jesus*: local config. `open_namespace_store` passes the local `SQLitePragmaPolicy` (read-safe subset) to `SQLiteWikiStore(..., read_only=True)`; the foreign `.parrot/wiki.json` is not read.
- [x] Where `checkpoint()` runs — *Owner: Jesus* (asked "what is better"): after `build` and after `ingest` only, never in `upsert --changed`. Both long commands write hundreds of slices under `wiki_write_lock`, so their end is the one moment the WAL is large and a writer already holds exclusivity. `upsert` runs per git commit, is sub-second and small (autocheckpoint covers it), and a `TRUNCATE` there would add latency to the post-commit hook and can be blocked by resident MCP readers.
