# TASK-4093: Wiki store: pre-migration backup/restore + cross-process migration lock

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4092
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 item (b) plus spike S6 (§3 M0: "migration-safety prototype — backup +
lock + gate vs a concurrent older runtime"). TASK-4092 added the `min_runtime_version`
stamp and the `WikiStoreVersionError` gate. This task adds the remaining safety rails
around the EXISTING auto-migration (`_maybe_migrate` → `_migrate`, store.py:1167/1444):

1. **Backup first, restore on failure** — a timestamped sidecar copy of the plane taken
   right before real migration work; any exception restores it and re-raises.
2. **Cross-process, Windows-safe migration lock** (codex S7): the store's
   `asyncio.Lock` (`self._init_lock`, store.py:1041) is per-instance, and the repo's
   file-lock precedent is POSIX-only — `knowledge/wiki/project.py:38-41` falls back to
   `fcntl = None`, and `wiki_write_lock` "degrades to a no-op and always yields True"
   on non-POSIX platforms (project.py:96-97). That pattern MUST NOT be reused (spec §7
   "File locking"). Use an `os.open(..., O_CREAT | O_EXCL)` sidecar lockfile with stale
   handling — atomic on every OS.
3. **Foreign / read-only planes keep never migrating**: `read_only=True` stores route
   every read through `_connect_immutable` / `_connect_readonly` (store.py:1203-1225) and
   never reach `_maybe_migrate`; federation opens foreign namespaces with
   `read_only=True` (federation.py:297-302). This task must not change that.

It also writes the S6 spike report codifying the concurrent-older-runtime scenario.

---

## Scope

- Add `os` / `time` imports and module helpers `_migration_lock_path`,
  `_try_acquire_migration_lock`, `_release_migration_lock`, constant
  `STALE_MIGRATION_LOCK_S`.
- Add `SQLiteWikiStore._backup_store(self) -> Path` (sync, run via `asyncio.to_thread`),
  `_restore_store(self, backup: Path) -> None` (sync), the async context manager
  `_migration_lock(self)`, and `_migrate_safely(self, conn)`.
- Route `_maybe_migrate` through `_migrate_safely` (replaces its direct `_migrate` call).
- Tests: failed migration restores the backup; migrate-then-older-runtime-open fails fast;
  the lock is exclusive across two processes and works with `fcntl` unavailable.
- Write `sdd/state/FEAT-633/spikes/S6-migration-safety.md`.

**NOT in scope**: the gate/stamp (TASK-4092, done); migrating read-only/foreign planes
(never); `wiki_write_lock` in project.py (untouched); backup pruning policy beyond what
is fixed below; other backends.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` | MODIFY | Backup/restore + O_EXCL migration lock around `_migrate` |
| `packages/ai-parrot/tests/knowledge/wiki/test_store_migration_safety.py` | CREATE | Backup/restore, skew, lock tests |
| `sdd/state/FEAT-633/spikes/S6-migration-safety.md` | CREATE | Spike S6 report |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiStoreBusy  # verified: store.py:948,284
from parrot.knowledge.wiki import store as store_mod  # module-level helpers patched in tests
# Created by TASK-4092 (dependency):
from parrot.knowledge.wiki.store import MIN_RUNTIME_KEY, WikiStoreVersionError, _running_version  # TASK-4092
import aiosqlite  # 0.22.1 installed; Connection.backup(target, *, pages=0, ...) exists (not needed — see Key Constraints)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
import errno                                                   # line 30 (anchor for new imports)
_FTS_TRIGGERS = frozenset({...})                               # line 241
_FTS_TABLES = ("pages_fts", "symbols_fts")                     # line 244
class WikiStoreBusy(sqlite3.OperationalError):                 # line 284
    def __init__(self, db_path: Path, operation: str, waited_seconds: float) -> None:  # line 297
_FTS_TOKEN_RE = re.compile(r"\w+", re.UNICODE)                 # line 309
class SQLiteWikiStore(BaseWikiStore):                          # line 948
    self._db_path: Path                                        # line 1009
    self._read_only: bool                                      # line 1010
    self._init_lock = asyncio.Lock()                           # line 1041 (per-instance only)
    self._policy: SQLitePragmaPolicy  (.busy_timeout_s)        # line 1043
    self._migrated = asyncio.Event()                           # line 1048
    async def _apply_pragmas(self, conn, *, writable)          # line 1074; `PRAGMA journal_mode = WAL` at 1096 (writable)
    async def _maybe_migrate(self, conn) -> None:              # line 1167
        async with self._init_lock:                            # line 1184
            if not self._migrated.is_set():                    # line 1185
                await self._migrate(conn)                      # line 1186
                self._migrated.set()                           # line 1187
    async def _read(self):                                     # line 1190; read_only branch 1203-1225 (never migrates)
    async def _migration_needed(self, conn) -> tuple[list[tuple[str, str, str]], bool]:  # line 1413 (pure reads)
    async def _migrate(self, conn) -> None:                    # line 1444 — _migrate_fts (1461), executescript (1467), ALTERs (1483), restamp (1492-1496)
    async def _migrate_fts(self, conn) -> None:                # line 1499 (DROP TABLE + executescript on legacy planes)
    async def _uses_legacy_fts(self, conn, table: str) -> bool:  # line 1558 (read-only probe, cached; _migrate_fts clears cache)
    # TASK-4092 adds: async def _check_runtime_gate(self, conn) -> None

# packages/ai-parrot/src/parrot/knowledge/wiki/project.py — the pattern NOT to reuse
try:  # POSIX only — see wiki_write_lock().                    # line 38
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX platform
    fcntl = None                                               # line 41
def wiki_write_lock(store_dir: Path, timeout: float = 0.0) -> Iterator[bool]:  # line 75; no-op w/o fcntl (docstring 96-97)
```
- Connections are autocommit (`isolation_level=None`, store.py:1125) and `_migrate` uses
  `executescript` (which COMMITs any open transaction in sqlite3) — a single wrapping
  transaction cannot make migration atomic; the backup is the rollback mechanism.
- Plane runs in WAL mode (module docstring store.py:9; pragma 1096): committed data may
  live in `wiki.db-wal`, so a plain copy of `wiki.db` alone is NOT a consistent backup.

### Does NOT Exist
- ~~`_backup_store`, `_restore_store`, `_migration_lock`, `_migrate_safely`, `_try_acquire_migration_lock`~~ — added here.
- ~~a cross-process lock in store.py~~ — only the per-instance `asyncio.Lock`.
- ~~`import os` / `import time` in store.py~~ — not imported today (imports at store.py:29-44).
- ~~`portalocker` / `filelock` dependencies~~ — not core deps; never add them (spec §5 "no new runtime dependency").
- ~~migration of read-only / foreign planes~~ — never.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/store.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_store_migration_safety.py", "action": "CREATE"},
    {"path": "sdd/state/FEAT-633/spikes/S6-migration-safety.md", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore._maybe_migrate",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore._migrate",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore._migration_needed",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore._uses_legacy_fts",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore._read",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#WikiStoreBusy",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#wiki_write_lock"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
```python
# atomic create-or-fail, identical semantics on POSIX and Windows
fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
```

### Key Constraints
- **Backup = SQLite online backup API, not a file copy** — decided by WAL mode (above).
  `_backup_store` opens its own `sqlite3` connections (`src.backup(dst)`) and is run with
  `await asyncio.to_thread(self._backup_store)` so the event loop never blocks (the spec
  skeleton fixes `def _backup_store(self) -> Path` as sync). The online backup is safe
  while this instance's aiosqlite connection is open and idle.
- **Restore** the same way in reverse (`backup.backup(db)`) after a best-effort
  `ROLLBACK` on `conn`; then re-raise the original exception.
- Backup path: `<db>.bak-<UTC %Y%m%dT%H%M%SZ>` beside the plane. Kept after a successful
  migration (it is the operator's downgrade path; migrations are rare — schema bumps
  only); never auto-deleted by this task.
- Backup + lock ONLY when there is real work: `_migration_needed` reports missing columns
  or a stale version, or `_uses_legacy_fts` is True for any `_FTS_TABLES` entry. A current
  plane keeps today's read-first, zero-write path (AC-4 of TASK-3218; the box comment in
  `_migrate`).
- After acquiring the lock: **re-probe** (another process may have migrated while we
  waited) and **re-run `_check_runtime_gate`** (a newer runtime may have stamped a higher
  minimum — the spec §4 concurrent-older-runtime case).
- Lock wait: poll with `await asyncio.sleep(0.1)` up to `self._policy.busy_timeout_s`; on
  timeout raise `WikiStoreBusy(self._db_path, "migrate", timeout)`.
- Stale lock: the file records `"<pid> <epoch>"`; a lock older than
  `STALE_MIGRATION_LOCK_S = 600.0` (mtime) is removed and acquisition retried once. Age
  (not PID liveness) is used because `os.kill(pid, 0)` is not a liveness probe on Windows.
- Always release in `finally` (`unlink(missing_ok=True)`).

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:1167-1187, 1413-1497`
- `packages/ai-parrot/src/parrot/knowledge/wiki/project.py:38-41, 75-110` — the anti-pattern

---

## Implementation Blueprint

### Steps (in order)
1. Add `import os` / `import time` and the module-level lock helpers — *why*: sync, picklable-free helpers are testable from a `multiprocessing` child.
2. Add `_backup_store` / `_restore_store` / `_migration_lock` / `_migrate_safely` to the class — *why*: spec §3 M7 (a)(b).
3. Replace `_maybe_migrate`'s direct `_migrate` call with `_migrate_safely` — *why*: single choke point for every migration.
4. Write tests, then the S6 report from their evidence — *why*: spec §3 M0 S6 → M7 mechanism validation.

### `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^import errno$' packages/ai-parrot/src/parrot/knowledge/wiki/store.py)
# AFTER — insert below `import errno` (verified: store.py:30); keep stdlib imports sorted
import os
import time
```
```python
# occurrences: 1 (verified: grep -c '_FTS_TOKEN_RE = re.compile(r"\\w+", re.UNICODE)' packages/ai-parrot/src/parrot/knowledge/wiki/store.py)
# AFTER — insert below `_FTS_TOKEN_RE = re.compile(r"\w+", re.UNICODE)` (verified: store.py:309)

#: FEAT-633: a migration lockfile older than this is presumed abandoned (crashed holder).
STALE_MIGRATION_LOCK_S: float = 600.0


def _migration_lock_path(db_path: Path) -> Path:
    """Sidecar lockfile guarding cross-process migration of ``db_path``."""
    return db_path.with_name(db_path.name + ".migrate.lock")


def _try_acquire_migration_lock(lock_path: Path, *, stale_after_s: float = STALE_MIGRATION_LOCK_S) -> bool:
    """Create ``lock_path`` atomically (O_CREAT|O_EXCL); True when this caller now holds it.

    Works identically on POSIX and Windows — deliberately NOT the fcntl pattern of
    ``project.py:38-41``, which degrades to a no-op without fcntl. A lock older than
    ``stale_after_s`` is removed and acquisition retried once.
    """
    for _attempt in range(2):
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            # FILL IN: stat mtime; if time.time() - mtime > stale_after_s → unlink(missing_ok=True),
            # logger.warning naming the path, continue; else return False. FileNotFoundError during
            # stat (holder just released) → continue — bounded by Key Constraints "Stale lock"
            raise NotImplementedError
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(f"{os.getpid()} {time.time()}")
        return True
    return False


def _release_migration_lock(lock_path: Path) -> None:
    """Remove the lockfile (idempotent)."""
    lock_path.unlink(missing_ok=True)
```
```python
# occurrences: 1 (verified: grep -c '                await self._migrate(conn)' packages/ai-parrot/src/parrot/knowledge/wiki/store.py)
# REPLACE — `                await self._migrate(conn)` inside `_maybe_migrate` (verified: store.py:1186) with:
                await self._migrate_safely(conn)
```
```python
# occurrences: 1 (verified: grep -c '                self._migrated.set()' packages/ai-parrot/src/parrot/knowledge/wiki/store.py)
# AFTER — insert below `                self._migrated.set()` (verified: store.py:1187), i.e. right after `_maybe_migrate`

    async def _has_migration_work(self, conn: aiosqlite.Connection) -> bool:
        """Pure-read probe: columns/version (``_migration_needed``) or a legacy FTS shape."""
        missing, version_stale = await self._migration_needed(conn)
        if missing or version_stale:
            return True
        return any([await self._uses_legacy_fts(conn, table) for table in _FTS_TABLES])

    async def _migrate_safely(self, conn: aiosqlite.Connection) -> None:
        """Run ``_migrate`` under the cross-process lock with a restorable backup.

        A current plane takes the unchanged read-first path (no lock, no backup, no write).
        """
        if not await self._has_migration_work(conn):
            await self._migrate(conn)  # still read-first: attrs/FTS-trigger self-heal probes only
            return
        async with self._migration_lock():
            await self._check_runtime_gate(conn)  # TASK-4092 — a newer runtime may have stamped while we waited
            if not await self._has_migration_work(conn):
                await self._migrate(conn)
                return
            backup = await asyncio.to_thread(self._backup_store)
            self.logger.info("migrating wiki plane %s (backup: %s)", self._db_path, backup)
            try:
                await self._migrate(conn)
            except BaseException:
                # FILL IN: best-effort `await conn.execute("ROLLBACK")` (ignore sqlite3.Error), then
                # `await asyncio.to_thread(self._restore_store, backup)`, log error naming backup, re-raise
                # — bounded by spec §5 "restores it on failure"
                raise

    @asynccontextmanager
    async def _migration_lock(self) -> AsyncIterator[None]:
        """Hold the cross-process migration lockfile; raise WikiStoreBusy after busy_timeout_s."""
        lock_path = _migration_lock_path(self._db_path)
        deadline = time.monotonic() + self._policy.busy_timeout_s
        while not _try_acquire_migration_lock(lock_path):
            if time.monotonic() >= deadline:
                raise WikiStoreBusy(self._db_path, "migrate", self._policy.busy_timeout_s)
            await asyncio.sleep(0.1)
        try:
            yield
        finally:
            _release_migration_lock(lock_path)

    def _backup_store(self) -> Path:
        """Online-backup the plane to ``<db>.bak-<UTC timestamp>``; run via ``asyncio.to_thread``.

        Uses the SQLite backup API (WAL-consistent), never a raw file copy.
        """
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = self._db_path.with_name(f"{self._db_path.name}.bak-{stamp}")
        # FILL IN: sqlite3.connect(self._db_path) as src, sqlite3.connect(backup) as dst → src.backup(dst);
        # close both explicitly (sqlite3's context manager does NOT close) — bounded by WAL constraint
        raise NotImplementedError

    def _restore_store(self, backup: Path) -> None:
        """Copy ``backup`` back over the plane with the backup API (reverse direction)."""
        # FILL IN: mirror of _backup_store (src=backup, dst=self._db_path); close both — bounded by Key Constraints
        raise NotImplementedError
```
**Why this shape**: `_migrate` itself is untouched — it stays read-first; every safety rail
wraps it at the single call site in `_maybe_migrate`. `datetime`/`timezone` are already
imported (store.py:38).

### `packages/ai-parrot/tests/knowledge/wiki/test_store_migration_safety.py` (CREATE)
```python
"""FEAT-633 M7 / spike S6 — migration backup, lock and skew (TASK-4093)."""

from __future__ import annotations

import multiprocessing
import sqlite3
import sys
from pathlib import Path

import pytest

from parrot.knowledge.wiki import store as store_mod
from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiStoreVersionError


async def _stale_plane(tmp_path: Path) -> Path:
    """A built plane whose schema_version is stale, so the next open migrates."""
    db = tmp_path / "wiki.db"
    await SQLiteWikiStore(db, "t").set_meta("k", "v")
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE meta SET value = '2' WHERE key = 'schema_version'")
    return db


async def test_migration_backup_and_restore(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Spec §4 — a failed migration restores the sidecar backup and re-raises."""
    db = await _stale_plane(tmp_path)

    async def boom(self, conn):  # noqa: ANN001
        await conn.execute("UPDATE meta SET value = 'corrupted' WHERE key = 'k'")
        raise RuntimeError("migration failed")

    monkeypatch.setattr(SQLiteWikiStore, "_migrate", boom)
    with pytest.raises(RuntimeError, match="migration failed"):
        await SQLiteWikiStore(db, "t").get_meta("k")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT value FROM meta WHERE key = 'k'").fetchone()[0] == "v"
    assert list(tmp_path.glob("wiki.db.bak-*"))
    assert not store_mod._migration_lock_path(db).exists()


async def test_current_plane_takes_no_backup(tmp_path: Path) -> None:
    # FILL IN: built (current) plane, reopen → no wiki.db.bak-* and no lockfile — bounded by "only when real work"
    raise NotImplementedError


async def test_store_migrate_then_old_open(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Spec §4 integration — migrate, then an older runtime (mocked version) fails fast."""
    db = await _stale_plane(tmp_path)
    await SQLiteWikiStore(db, "t").get_meta("k")  # migrates + stamps (TASK-4092)
    monkeypatch.setattr(store_mod, "_running_version", lambda: "0.0.1")
    with pytest.raises(WikiStoreVersionError):
        await SQLiteWikiStore(db, "t").get_meta("k")


def _hold_lock(lock_path: str, acquired, release) -> None:  # noqa: ANN001 — multiprocessing child
    from parrot.knowledge.wiki import store as child_store

    acquired.value = int(child_store._try_acquire_migration_lock(Path(lock_path)))
    release.wait(10)
    child_store._release_migration_lock(Path(lock_path))


def test_migration_lock_is_exclusive_across_processes(tmp_path: Path) -> None:
    lock = tmp_path / "wiki.db.migrate.lock"
    ctx = multiprocessing.get_context("spawn")
    acquired, release = ctx.Value("i", -1), ctx.Event()
    child = ctx.Process(target=_hold_lock, args=(str(lock), acquired, release))
    child.start()
    # FILL IN: wait until acquired.value != -1 (bounded poll ≤10s); assert == 1; assert
    # store_mod._try_acquire_migration_lock(lock) is False while held; release.set(); join; assert
    # acquisition now succeeds — bounded by spec §3 M7 "cross-process"
    raise NotImplementedError


def test_migration_lock_windows_safe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Spec §4 — not a no-op when fcntl is unavailable."""
    monkeypatch.setitem(sys.modules, "fcntl", None)  # any `import fcntl` now raises ImportError
    lock = tmp_path / "x.lock"
    assert store_mod._try_acquire_migration_lock(lock) is True
    assert store_mod._try_acquire_migration_lock(lock) is False
    store_mod._release_migration_lock(lock)


def test_stale_lock_is_reclaimed(tmp_path: Path) -> None:
    # FILL IN: create lock, os.utime it 2*STALE_MIGRATION_LOCK_S in the past → acquire returns True — bounded by Key Constraints
    raise NotImplementedError


async def test_read_only_plane_never_migrates(tmp_path: Path) -> None:
    # FILL IN: stale plane opened read_only=True → get_meta works, schema_version still "2", no backup,
    # no lockfile — bounded by spec §3 M7 "Foreign/read-only stores keep never migrating"
    raise NotImplementedError
```

### `sdd/state/FEAT-633/spikes/S6-migration-safety.md` (CREATE)
```markdown
# Spike S6 — Wiki store migration safety (FEAT-633)

**Date**: <YYYY-MM-DD> · **Task**: TASK-4093 · **Status**: <pass | fail>

## Question
Does backup + O_EXCL lock + min-runtime gate keep a plane safe when a newer and an older
runtime open it concurrently (spec §3 M0 S6 → M7)?

## Mechanism under test
- Backup: SQLite online backup API to `<db>.bak-<UTC>` (WAL-consistent), restore on failure.
- Lock: `<db>.migrate.lock` via `os.open(O_CREAT|O_EXCL)`; stale after 600 s; why not
  `project.py:38-41` (fcntl no-op off POSIX).
- Gate: `min_runtime_version` meta row (TASK-4092), re-checked after the lock is acquired.

## Evidence
<!-- FILL IN: the pytest command lines + pass output for test_store_migration_safety.py and
     test_store_runtime_gate.py; platforms exercised (Linux; Windows via CI if available) -->

## Scenarios
| Scenario | Expected | Observed |
|---|---|---|
| failed migration | backup restored, error re-raised | <!-- FILL IN --> |
| newer migrates, older opens | WikiStoreVersionError naming both versions | <!-- FILL IN --> |
| two processes race the lock | exactly one holds it | <!-- FILL IN --> |
| fcntl unavailable | lock still exclusive | <!-- FILL IN --> |
| read-only/foreign plane | never migrated, no backup/lock | <!-- FILL IN --> |

## Limitations
- Runtimes predating FEAT-633 ignore the gate (spec §7).
- <!-- FILL IN: anything observed (e.g. backup size/time on a large plane) -->

## Verdict
<!-- FILL IN: mechanism confirmed / changes required for M7 -->
```

### FILL IN checklist
- [ ] `store.py::_try_acquire_migration_lock` — stale handling; bounded by Key Constraints "Stale lock"
- [ ] `store.py::SQLiteWikiStore._migrate_safely` — rollback + restore + re-raise; bounded by spec §5
- [ ] `store.py::SQLiteWikiStore._backup_store` / `_restore_store` — backup API both ways; bounded by WAL constraint
- [ ] `test_store_migration_safety.py` — the four FILL IN tests
- [ ] `S6-migration-safety.md` — evidence, observed column, verdict (from real test runs only)

---

## Acceptance Criteria

- [ ] Before real migration work the plane is backed up to `<db>.bak-<UTC>` via the SQLite backup API; a failing migration restores it and re-raises (spec §4 `test_migration_backup_and_restore`, §5).
- [ ] Migration runs under an `O_CREAT|O_EXCL` sidecar lockfile that is exclusive across processes and is NOT a no-op without `fcntl` (spec §4 `test_migration_lock_windows_safe`, §7 "File locking").
- [ ] After acquiring the lock the store re-probes and re-checks the runtime gate; migrate-then-older-open fails fast (spec §4 `test_store_migrate_then_old_open`).
- [ ] Current planes take no lock and no backup (read-first path unchanged); read-only/foreign planes never migrate.
- [ ] `sdd/state/FEAT-633/spikes/S6-migration-safety.md` records real evidence.
- [ ] Existing store tests still pass; `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/store.py` clean.

---

## Validation Commands

Run from the feature worktree with `PYTHONPATH=packages/ai-parrot/src` (the shared venv is
editable-installed against the main checkout).

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_store_migration_safety.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_store_meta.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_sqlite_fts_external_content.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_store_attrs.py -q`

---

## Test Specification

See the CREATE block for `packages/ai-parrot/tests/knowledge/wiki/test_store_migration_safety.py`
(`test_migration_backup_and_restore`, `test_migration_lock_windows_safe`,
`test_store_migrate_then_old_open` per spec §4, plus cross-process exclusivity, stale-lock,
no-work and read-only cases). The multiprocessing child uses the `spawn` context so it runs
on every OS.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug parrot-installer --feature-id FEAT-633`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/parrot-installer.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/parrot-installer.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4093 parrot-installer verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
