# TASK-4092: Wiki store: min_runtime_version stamp + WikiStoreVersionError gate

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Discovered-from**: `issue:f249c19e8a4d`
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 items (a)(c)(d) — here (c) the stamp and (d) the gate; backup + lock are
TASK-4093. With a managed runtime (`~/.parrot/venv`) and project venvs coexisting, two
different ai-parrot versions can open the same `wiki.db`. `SQLiteWikiStore` already
auto-migrates silently on `schema_version` mismatch (`_maybe_migrate` → `_migrate`);
nothing ever refuses an open (spec §6 "Today a version mismatch is ALWAYS migrated
silently"). The owner's skew policy (spec §8 "Skew concurrency guard") is a **store-side
version gate** *[rev 0.5 C24 / D8]*: plane creation and migration stamp `min_runtime_version` into the
existing `meta` key/value table, and every connection — read-write AND read-only — first checks
the stored `schema_version`; a runtime with an older `SCHEMA_VERSION` fails fast with
`WikiStoreVersionError` naming both schemas, the stamped release and the fix, so a newer plane is
never migrated and re-stamped downward (ledger `issue:f249c19e8a4d`). `min_runtime_version` is
informational: quoted in the message, never compared (owner, 2026-10-20: a release-number gate
was too strict).

**Known limitation (document in the docstring)**: only runtimes that contain this task
honour the gate — a pre-FEAT-633 runtime has no gate (spec §7 "Version-skew
auto-migration").

**Subclass planes**: `LedgerStore` (`ledger.db`, `knowledge/wiki/ledger/store.py:24`) and
`SchemaStore` (`schema.db`, `knowledge/wiki/schema/store.py:48`) are `SQLiteWikiStore`
subclasses that go through `_write`/`_read` → `_open`, so they are gated and stamped by this
task too — no extra code needed.

---

## Readiness review — 2026-10-19 (dev 9f51c7735)
- Refreshed against dev 9f51c7735: `store.py` anchors ≥ line 948 shifted +144 (6791d81ce inserted the `WikiBackendSpec` registry at store.py:539-694; the `SQLiteWikiStore` body is byte-identical and every blueprint `grep -c` count still matches); `version.py:8` is now `"1.2.3"`; `asyncio_mode` is at `pyproject.toml:1048`; Context notes that `ledger.db`/`schema.db` subclasses are gated.
- Resolved by spec rev 0.5 (2026-10-20, C24 / D8; D8 corrected by the owner the same day, dev `549b77de7`: gate by schema number) — build this:
  - **Stamp at creation and at migration.** `_ensure_schema` writes `min_runtime_version = _running_version()` next to `schema_version` in the fresh-plane block (same `INSERT OR IGNORE`, store.py:1300-1303). `_migrate` keeps its upsert inside `if version_stale:`. The stamp is informational: quoted in the error, never compared — a plane created or migrated by 1.2.4 opens in 1.2.3 when both have the same `SCHEMA_VERSION` (comparing release numbers was too strict). There is no release-tuple helper and no release-number test.
  - **Refuse a downgrade.** `_check_runtime_gate` reads `schema_version`. When it is an integer greater than `int(SCHEMA_VERSION)` it raises `WikiStoreVersionError.newer_schema(...)` and nothing is written. The gate runs on every connection, before `_ensure_schema` and `_maybe_migrate`, so neither the `_migrate` restamp (store.py:1637-1638) nor the `rebuild_index` restamp (store.py:2776-2777, also `SQLiteWikiStore`, reached through `_write` → `_open`) can write a lower version. `_migration_needed` (stale check :1585) stays a pure probe and is not changed. A non-integer value logs a warning and opens; `_migration_needed` then treats it as stale, as today. Closes ledger `issue:f249c19e8a4d`. Scope, Key Constraints, blueprint, tests and ACs are updated accordingly.
  - The unwritable-directory rule (backup + lockfile) is TASK-4093.
  - Known bypass, out of scope: `SourceCollectionManager._connect` (`sources.py:796-811`) and `_migrate_sources_columns` (`sources.py:983-1003`) open `wiki.db` with plain `sqlite3`. The checkpoint and ledger `issue:1555e747bcb9` call it `SourceRegistry` — no such class exists in any package (`git grep` over `packages/`); `SourceCollectionManager` is `sources.py:73`. Recorded under NOT in scope.
- Anchor corrections (dev 69fb12a41): every `store.py` anchor in this file re-checked and unchanged; `sources.py:795` is a blank line, so `_connect` is :796-811.
---

## Scope

- Add module constant `MIN_RUNTIME_KEY = "min_runtime_version"`.
- Add `WikiStoreVersionError(RuntimeError)` — NOT an `sqlite3.OperationalError` subclass
  (`_read` catches `OperationalError` to degrade to read-only, store.py:1377; the gate
  must never be swallowed by that ladder).
- Add module helper `_running_version() -> str` (reads `parrot.version.__version__` at
  call time — the test seam). No release-number parsing: the gate never compares releases. *[rev 0.5]*
- Add `SQLiteWikiStore._check_runtime_gate(conn)` and call it in `_open`,
  `_connect_immutable` and both rungs of `_connect_readonly`, BEFORE the connection is
  used/yielded.
- In `_migrate`, stamp `min_runtime_version = _running_version()` alongside the
  `schema_version` restamp.
- *[rev 0.5 C24 / D8]* In `_ensure_schema`, stamp `min_runtime_version = _running_version()`
  next to the fresh-plane `schema_version` insert (store.py:1300-1303).
- *[rev 0.5 C24 / D8]* In `_check_runtime_gate`, refuse a stored `schema_version` greater than
  `SCHEMA_VERSION`, compared as integers, with `WikiStoreVersionError.newer_schema(...)`, before
  anything is written — so it is never migrated and re-stamped downward (ledger
  `issue:f249c19e8a4d`). That is the whole gate; `min_runtime_version` is read only for the message.
- Tests in a new file.
- Close ledger `issue:f249c19e8a4d` when done.

**NOT in scope**: pre-migration backup/restore and the cross-process migration lock
(TASK-4093); stamping from `rebuild_index` (store.py:2764-2780 restamps `schema_version`
but is not a migration — leave it; it already goes through `_write` → `_open`, so it is
gated, and the downgrade refusal stops it before its restamp *[rev 0.5]*); `PRAGMA user_version` (spec: never introduced); other backends
(`InMemoryWikiStore`, Arango, Postgres); the unwritable-directory error (TASK-4093) *[rev 0.5]*;
gating `SourceCollectionManager._connect` (`sources.py:796-811`, plain `sqlite3`; also
`_migrate_sources_columns`, `sources.py:983-1003`) — a known bypass, out of scope per spec rev 0.5
C24 / D8, recorded as ledger `issue:1555e747bcb9` (filed under the checkpoint's old class name; see
the readiness section).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` | MODIFY | Gate constant, error, helper, schema check (newer `schema_version`), stamps at creation + migration *[rev 0.5]* |
| `packages/ai-parrot/tests/knowledge/wiki/test_store_runtime_gate.py` | CREATE | Gate + stamp tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot import version as _parrot_version  # verified: packages/ai-parrot/src/parrot/version.py:8 (__version__ = "1.2.3"); parrot/__init__.py already imports .version → no cycle
from parrot.knowledge.wiki.store import SCHEMA_VERSION, SQLiteWikiStore  # verified: store.py:51,1092
import aiosqlite  # verified: store.py:43
import sqlite3  # verified: store.py:33
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
SCHEMA_VERSION = "3"                                                        # line 51
class WikiStoreBusy(sqlite3.OperationalError):                              # line 284
class AttrsUnsupportedError(RuntimeError):                                  # line 429 — style precedent for the new error
class SQLiteWikiStore(BaseWikiStore):                                       # line 1092
    def __init__(self, db_path, wiki_name="", *, read_only=False, sqlite_policy=None, persistent_writer=False)  # line 1144-1152
    def _assert_writable(self) -> None:                                     # line 1205 (raise at 1212)
    async def _apply_pragmas(self, conn, *, writable: bool) -> None:        # line 1218
    async def _open(self, *, writable: bool) -> AsyncIterator[aiosqlite.Connection]:  # line 1252; connect 1266; pragmas 1272; _ensure_schema 1274
    async def _ensure_schema(self, conn) -> None:                           # line 1277 (fresh plane: INSERT OR IGNORE schema_version 1300-1303; stamp min_runtime_version here too *[rev 0.5]*)
    async def _maybe_migrate(self, conn) -> None:                           # line 1311
    async def _read(self):                                                  # line 1334; `except sqlite3.OperationalError` at 1377
    async def _connect_immutable(self):                                     # line 1445; connect 1455-1457; _log_read_only_once 1461
    async def _connect_readonly(self):                                      # line 1465; mode=ro rung 1492-1498; immutable rung 1527-1534
    async def _migration_needed(self, conn) -> tuple[list[...], bool]:      # line 1557 (reads schema_version 1581; stale check 1585)
    async def _migrate(self, conn) -> None:                                 # line 1588; restamp 1636-1640; commit 1641
    async def get_meta(self, key: str) -> Optional[str]:                    # line 2346
    async def set_meta(self, key: str, value: str) -> None:                 # line 2353
    async def rebuild_index(self) -> dict[str, Any]:                        # line 2764 (restamp 2775-2779 — NOT a migration; covered by the downgrade refusal *[rev 0.5]*)
WikiStore = SQLiteWikiStore                                                 # line 2806
```
- Foreign planes are opened `read_only=True` (`federation.py:297-302`); they go through
  `_connect_immutable` / `_connect_readonly` only (store.py:1347-1369) and never migrate.
- Tests run with `asyncio_mode = "auto"` (packages/ai-parrot/pyproject.toml:1048) — plain
  `async def test_…` (precedent: `tests/knowledge/wiki/test_store_meta.py`).

### Does NOT Exist
- ~~`MIN_RUNTIME_KEY`, `WikiStoreVersionError`, `_check_runtime_gate`, `_running_version`~~ — added here.
- ~~`PRAGMA user_version`~~ anywhere in `knowledge/wiki/` — never introduce it.
- ~~`packaging` as a core ai-parrot dependency~~ — absent from `packages/ai-parrot/pyproject.toml`; do not import it.
- ~~any open-time version refusal today~~ — this task adds the first one.
- ~~a downgrade refusal today~~ — `_migration_needed` treats any `!=` as stale (store.py:1585) and `_migrate` overwrites the row (:1637-1638); ledger `issue:f249c19e8a4d` — fixed here. *[rev 0.5]*
- ~~a `min_runtime_version` stamp in `_ensure_schema`~~ — today it writes only `schema_version` (:1300-1303). Added here. *[rev 0.5]*
- ~~`_release_tuple` / any release-number comparison~~ — never add one: the gate is the schema number (rev 0.5 D8, owner correction).
- ~~`_backup_store` / migration lock~~ — TASK-4093.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/store.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_store_runtime_gate.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore._open",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore._ensure_schema",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore._migration_needed",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore._read",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore._connect_immutable",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore._connect_readonly",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore._migrate",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore._assert_writable",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore.get_meta",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore.set_meta",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#AttrsUnsupportedError"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
```python
# store.py:1581-1582 — reading one meta row
async with conn.execute("SELECT value FROM meta WHERE key = 'schema_version'") as cur:
    row = await cur.fetchone()
```

### Key Constraints
- Gate runs on EVERY connection (one indexed SELECT) — never latch it per instance: a newer
  runtime may migrate the plane while this instance is alive.
- A plane with no `meta` table yet (brand-new file, `_open` before `_ensure_schema`) or no
  `schema_version` row opens normally. A missing `min_runtime_version` row (pre-FEAT-633 plane)
  changes nothing; the message then says "unknown". *[rev 0.5]*
- In `_open`, check AFTER `_apply_pragmas` (so `busy_timeout` covers the SELECT) and
  BEFORE `_ensure_schema` (so an older runtime writes nothing to a newer plane).
- Stamp in two places (rev 0.5 C24 / D8): the fresh-plane block of `_ensure_schema` (`INSERT OR
  IGNORE`, so an existing row is kept) and `_migrate`'s `if version_stale:` block. A pre-FEAT-633
  plane whose schema did not change stays unstamped. *[rev 0.5]*
- The gate: a stored `schema_version` greater than `SCHEMA_VERSION` (both as ints, `"10" > "3"`;
  read the module global at call time) raises `WikiStoreVersionError` in `_check_runtime_gate`, on
  read-write and read-only connections, so an older runtime never migrates or restamps a newer
  plane. **This is the whole gate.** `min_runtime_version` is never compared: a same-schema plane
  stamped by a newer release (e.g. "99.0.0") opens normally. *[rev 0.5]*
- Resolved (PR #1746 review, 2026-10-20): the refusal is raised through the classmethod
  `WikiStoreVersionError.newer_schema(db_path, stored, store_minimum, running)` — the one named
  constructor callers and tests use; the message is fixed in the blueprint.
- A missing or non-integer `schema_version` is not refused: a non-integer value logs a warning
  and opens, and `_migration_needed` keeps calling it stale (migrate, as today). Failing closed
  on garbage would brick a plane with no fix path. *[rev 0.5; PR #1746 review]*
- Error message must contain: the store path, the store's schema version, the running
  `SCHEMA_VERSION`, the stamped `min_runtime_version` (or "unknown"), the running ai-parrot
  version, and the fix `parrot self update` (managed runtime) / `parrot self add --here`
  (project venv). *[rev 0.5]*

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:1251-1275, 1444-1539, 1588-1641`

---

## Implementation Blueprint

### Steps (in order)
1. Add the constant, helper and error class — *why*: spec §3 M7 skeleton names are fixed.
2. Add `_check_runtime_gate` to `SQLiteWikiStore` — *why*: one implementation for all four connect sites (newer `schema_version` refusal, rev 0.5 C24 / D8).
3. Call it in `_open`, `_connect_immutable`, and both `_connect_readonly` rungs — *why*: spec §5 "read-only paths included".
4. Stamp in `_migrate` and in `_ensure_schema`; `_check_runtime_gate` compares schema numbers only — *why*: spec §3 M7 (c) and rev 0.5 C24 / D8 (1)(2). *[rev 0.5]*
5. Write tests — *why*: spec §4 `test_gate_blocks_older_runtime`; §5 "A newer `schema_version` is refused, not re-stamped".

### `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'SCHEMA_VERSION = "3"' packages/ai-parrot/src/parrot/knowledge/wiki/store.py)
# AFTER — insert below `SCHEMA_VERSION = "3"` (verified: store.py:51)

#: FEAT-633: the ai-parrot release that last created or migrated a plane; a ``meta`` row
#: stamped by ``SQLiteWikiStore._ensure_schema`` and ``_migrate``. Informational only [rev 0.5]:
#: quoted in WikiStoreVersionError, never compared (the gate is the schema number).
MIN_RUNTIME_KEY = "min_runtime_version"


def _running_version() -> str:
    """The running ai-parrot version, read at call time (tests patch ``parrot.version.__version__``)."""
    from parrot import version as _parrot_version  # stdlib-only module; parrot/__init__ already loaded it

    return _parrot_version.__version__
```
```python
# occurrences: 1 (verified: grep -c 'class AttrsUnsupportedError(RuntimeError):' packages/ai-parrot/src/parrot/knowledge/wiki/store.py)
# AFTER — insert below the AttrsUnsupportedError class body (verified: store.py:429-430)


class WikiStoreVersionError(RuntimeError):
    """The plane's ``schema_version`` is newer than the running ``SCHEMA_VERSION`` [rev 0.5 C24 / D8].

    Decided by schema number only. ``store_minimum`` (the plane's ``min_runtime_version`` stamp)
    is quoted in the message, never compared. Deliberately NOT a :class:`sqlite3.OperationalError`:
    the read ladder in ``SQLiteWikiStore._read`` degrades on OperationalError, and this must never degrade.
    """

    def __init__(self, db_path: Path, store_schema: str, store_minimum: Optional[str], running: str) -> None:
        self.db_path = db_path
        self.store_schema = store_schema
        self.store_minimum = store_minimum
        self.running = running
        written_by = store_minimum or "unknown"
        upgrade_to = f"ai-parrot >= {store_minimum}" if store_minimum else "a newer ai-parrot"
        super().__init__(
            f"wiki store {db_path} has schema version {store_schema}, newer than this runtime's "
            f"{SCHEMA_VERSION} (ai-parrot {running}). This store was written by ai-parrot {written_by}; "
            f"upgrade to {upgrade_to}: `parrot self update` (managed runtime) or `parrot self add --here` (project venv)."
        )

    @classmethod
    def newer_schema(
        cls, db_path: Path, stored: str, store_minimum: Optional[str], running: str
    ) -> "WikiStoreVersionError":
        """Rev 0.5 C24 / D8: the plane's ``schema_version`` is newer than ``SCHEMA_VERSION`` (the only refusal)."""
        return cls(db_path, stored, store_minimum, running)
```
```python
# occurrences: 1 (verified: grep -c '            raise PermissionError(f"read-only wiki store: {self._db_path}")' packages/ai-parrot/src/parrot/knowledge/wiki/store.py)
# AFTER — insert below that line, i.e. after `_assert_writable` (verified: store.py:1212)

    async def _check_runtime_gate(self, conn: aiosqlite.Connection) -> None:
        """Refuse the plane when its ``schema_version`` is newer than the running ``SCHEMA_VERSION``.

        The schema comparison is the whole gate [rev 0.5]; ``min_runtime_version`` is read only
        for the error message. One indexed read per connection (a second one only on refusal).
        A plane without a ``meta`` table (brand new) or without a ``schema_version`` row passes;
        a non-integer value logs a warning and passes (``_migration_needed`` then treats it as stale).

        Raises:
            WikiStoreVersionError: the store has a newer schema than this runtime.
        """
        try:
            async with conn.execute("SELECT value FROM meta WHERE key = 'schema_version'") as cur:
                row = await cur.fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc):
                return
            raise
        if row is None:
            return
        # FILL IN [rev 0.5]: int(row[0]) — ValueError/TypeError → self.logger.warning + return (fail open,
        # see Key Constraints); not greater than int(SCHEMA_VERSION) → return; otherwise read the
        # MIN_RUNTIME_KEY row the same way (None when absent) and raise
        # WikiStoreVersionError.newer_schema(self._db_path, str(row[0]), <min value or None>, _running_version()).
        # Never compare min_runtime_version.
        raise NotImplementedError
```
```python
# [rev 0.5] occurrences: 1 (verified: grep -c '                    ("schema_version", SCHEMA_VERSION),' packages/ai-parrot/src/parrot/knowledge/wiki/store.py)
# AFTER — the closing `                )` of the fresh-plane schema_version insert in `_ensure_schema`
# (verified: store.py:1300-1303), still inside `async with self._init_lock:` and before the wiki_name insert
                await conn.execute(
                    "INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)",
                    (MIN_RUNTIME_KEY, _running_version()),
                )
```
**Why**: mirrors the adjacent fresh-plane `schema_version`
insert; `OR IGNORE` keeps an existing stamp, which is informational anyway.
```python
# occurrences: 1 (verified: grep -c '        await self._apply_pragmas(conn, writable=writable)' packages/ai-parrot/src/parrot/knowledge/wiki/store.py)
# AFTER — insert below that line in `_open` (verified: store.py:1272), BEFORE `if writable: await self._ensure_schema(conn)`
            await self._check_runtime_gate(conn)
```
```python
# occurrences: 1 (verified: grep -c '^            self._log_read_only_once()$' packages/ai-parrot/src/parrot/knowledge/wiki/store.py)
# AFTER — insert below the 12-space-indented `self._log_read_only_once()` in `_connect_immutable` (verified: store.py:1461)
            await self._check_runtime_gate(conn)
```
```python
# occurrences: 2 (verified: grep -c '^                self._log_read_only_once()$' packages/ai-parrot/src/parrot/knowledge/wiki/store.py)
# AFTER — insert below EACH of the two 16-space occurrences in `_connect_readonly`, disambiguated by context:
#   (1) store.py:1496, in the rung opened by
#       `async with aiosqlite.connect(f"{base}?mode=ro", uri=True, timeout=self._policy.busy_timeout_s) as conn:` (store.py:1492)
#   (2) store.py:1532, in the rung opened by
#       `f"{base}?mode=ro&immutable=1", uri=True, timeout=self._policy.busy_timeout_s` (16-space indent, store.py:1528)
# Both insertions go BEFORE `yielded = True` (store.py:1497 / 1533) so a gate error is raised, not swallowed.
                await self._check_runtime_gate(conn)
```
```python
# occurrences: 2 (verified: grep -c '                (SCHEMA_VERSION,),' packages/ai-parrot/src/parrot/knowledge/wiki/store.py)
# AFTER — the `_migrate` occurrence only (store.py:1636-1640), disambiguated by its context:
#             await conn.execute(
#                 "INSERT INTO meta (key, value) VALUES ('schema_version', ?)"
#                 " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
#                 (SCHEMA_VERSION,),
#             )
#         await conn.commit()          <- store.py:1641; the OTHER occurrence (store.py:2778) is rebuild_index — leave it
# Insert after the closing `            )` at store.py:1640, still inside `if version_stale:`
            await conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (MIN_RUNTIME_KEY, _running_version()),
            )
```
**Why**: `_migrate` only restamps a stale schema (older, missing or non-integer — a newer one
was refused by the gate), so the upsert records the release that brought the plane to this
schema. The value is informational and never compared. *[rev 0.5]*

### `packages/ai-parrot/tests/knowledge/wiki/test_store_runtime_gate.py` (CREATE)
```python
"""FEAT-633 M7 — wiki store version gate (TASK-4092): schema number only [rev 0.5]."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from parrot.knowledge.wiki import store as store_mod
from parrot.knowledge.wiki.store import MIN_RUNTIME_KEY, SQLiteWikiStore, WikiStoreVersionError


async def _built_plane(tmp_path: Path) -> Path:
    db = tmp_path / "wiki.db"
    await SQLiteWikiStore(db, "t").set_meta("k", "v")  # builds schema (and stamps min_runtime_version — rev 0.5 C24 / D8)
    return db


def _stamp(db: Path, key: str, value: str) -> None:
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def _meta(db: Path, key: str) -> str | None:
    with sqlite3.connect(db) as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return None if row is None else row[0]


async def test_unstamped_plane_opens(tmp_path: Path) -> None:
    """A pre-FEAT-633 plane (no min_runtime_version row) opens normally."""
    db = await _built_plane(tmp_path)
    with sqlite3.connect(db) as conn:  # [rev 0.5] creation now stamps; drop the row to mimic a pre-FEAT-633 plane
        conn.execute("DELETE FROM meta WHERE key = ?", (MIN_RUNTIME_KEY,))
    assert await SQLiteWikiStore(db, "t").get_meta("k") == "v"


async def test_newer_schema_version_refused(tmp_path: Path) -> None:
    """Rev 0.5 C24 / issue:f249c19e8a4d — a newer schema_version is refused, not re-stamped downward."""
    db = await _built_plane(tmp_path)
    newer = str(int(store_mod.SCHEMA_VERSION) + 7)  # "10" sorts below "3" as text — proves integer comparison
    _stamp(db, "schema_version", newer)
    with pytest.raises(WikiStoreVersionError, match=f"schema version {newer}, newer than this runtime's"):
        await SQLiteWikiStore(db, "t").get_meta("k")
    # FILL IN: same refusal for SQLiteWikiStore(db, "t", read_only=True).get_meta — bounded by spec §5 "read-only paths included"
    assert _meta(db, "schema_version") == newer


async def test_fresh_plane_stamped_at_creation(tmp_path: Path) -> None:
    """[rev 0.5 C24 / D8 (1)] — _ensure_schema stamps min_runtime_version on a brand-new plane."""
    db = await _built_plane(tmp_path)
    assert await SQLiteWikiStore(db, "t").get_meta(MIN_RUNTIME_KEY) == store_mod._running_version()


async def test_gate_blocks_older_runtime(tmp_path: Path) -> None:
    """Spec §4 — a higher schema_version raises; the message has both schemas, the stamp and the fix."""
    db = await _built_plane(tmp_path)
    _stamp(db, MIN_RUNTIME_KEY, "9.9.9")
    _stamp(db, "schema_version", "99")
    with pytest.raises(WikiStoreVersionError) as info:
        await SQLiteWikiStore(db, "t").get_meta("k")
    message = str(info.value)
    assert "schema version 99" in message and f"runtime's {store_mod.SCHEMA_VERSION}" in message
    assert "9.9.9" in message and store_mod._running_version() in message and "parrot self update" in message


async def test_gate_blocks_read_only_store(tmp_path: Path) -> None:
    # FILL IN: _stamp schema_version "99"; SQLiteWikiStore(db, "t", read_only=True).get_meta → WikiStoreVersionError
    # (covers _connect_immutable / _connect_readonly) — bounded by spec §5 "read-only paths included"
    raise NotImplementedError


async def test_gate_blocks_writes_before_any_write(tmp_path: Path) -> None:
    # FILL IN [rev 0.5]: _stamp schema_version "99"; set_meta("k", "w") and rebuild_index() each raise
    # WikiStoreVersionError (store_schema == "99"); afterwards (plain sqlite3) schema_version is still "99"
    # and "k" is "v" — no migrate, no rebuild_index restamp — bounded by spec §3 M7 (d) and rev 0.5 D8 (2)
    raise NotImplementedError


async def test_newer_release_same_schema_opens(tmp_path: Path) -> None:
    """[rev 0.5 D8 corrected] — min_runtime_version is never compared: a same-schema plane opens."""
    db = await _built_plane(tmp_path)
    _stamp(db, MIN_RUNTIME_KEY, "99.0.0")
    assert await SQLiteWikiStore(db, "t").get_meta("k") == "v"
    assert await SQLiteWikiStore(db, "t", read_only=True).get_meta("k") == "v"
    await SQLiteWikiStore(db, "t").set_meta("k", "w")
    assert await SQLiteWikiStore(db, "t").get_meta(MIN_RUNTIME_KEY) == "99.0.0"  # an open never restamps


async def test_migration_stamps_running_version(tmp_path: Path) -> None:
    """A stale schema_version migrates and stamps min_runtime_version = running version."""
    db = await _built_plane(tmp_path)
    _stamp(db, MIN_RUNTIME_KEY, "0.0.1")  # older stamp, so only `_migrate`'s upsert can produce the running version
    _stamp(db, "schema_version", "2")
    await SQLiteWikiStore(db, "t").get_meta("k")  # first open migrates
    assert await SQLiteWikiStore(db, "t").get_meta(MIN_RUNTIME_KEY) == store_mod._running_version()


async def test_non_integer_schema_still_migrates(tmp_path: Path) -> None:
    """[rev 0.5] — a non-integer stored schema_version is not refused: it is stale and migrates, as today."""
    db = await _built_plane(tmp_path)
    _stamp(db, "schema_version", "garbage")
    await SQLiteWikiStore(db, "t").get_meta("k")  # first open migrates
    assert await SQLiteWikiStore(db, "t").get_meta("schema_version") == store_mod.SCHEMA_VERSION
```

### FILL IN checklist
- [ ] `store.py::SQLiteWikiStore._check_runtime_gate` — schema-number compare + fail-open on a non-integer value; bounded by Key Constraints *[rev 0.5]*
- [ ] `test_store_runtime_gate.py` — the two FILL IN tests (read-only, writes) plus the read-only line in `test_newer_schema_version_refused`; bounded by spec §5 / §3 M7 (d) / rev 0.5 D8 *[rev 0.5]*

---

## Acceptance Criteria

- [ ] `MIN_RUNTIME_KEY`, `WikiStoreVersionError(RuntimeError)`, `_check_runtime_gate` exist with the names fixed by spec §3 M7.
- [ ] A plane whose stored `schema_version` is an integer greater than the running `SCHEMA_VERSION` raises `WikiStoreVersionError` on `_open` AND on the read-only connects, before any write (spec §5 "read-only paths included"; §4 `test_gate_blocks_older_runtime`). *[rev 0.5]*
- [ ] The message names both schemas, the stamped `min_runtime_version` (or "unknown"), the running version and the fix (`parrot self update` / `parrot self add --here`). *[rev 0.5]*
- [ ] A higher `min_runtime_version` with the same `schema_version` opens normally, read-write and read-only — the stamp is never compared (spec rev 0.5 D8). *[rev 0.5]*
- [ ] A non-integer stored `schema_version` is not refused; it migrates as today. *[rev 0.5]*
- [ ] `_migrate` stamps `min_runtime_version` alongside `schema_version`; unstamped (pre-FEAT-633) and brand-new planes open normally.
- [ ] *[rev 0.5 C24 / D8 (1)]* `_ensure_schema` stamps `min_runtime_version` on a brand-new plane (`test_fresh_plane_stamped_at_creation`).
- [ ] *[rev 0.5 C24 / D8 (2)]* A stored `schema_version` greater than `SCHEMA_VERSION`, compared as integers, raises `WikiStoreVersionError` and is left unchanged — nothing is written: no migrate, no `rebuild_index` restamp (`test_newer_schema_version_refused`, `test_gate_blocks_writes_before_any_write`; spec §5 "A newer `schema_version` is refused, not re-stamped").
- [ ] Ledger `issue:f249c19e8a4d` is closed: `wikitoolkit ledger close issue:f249c19e8a4d --resolved-by task:TASK-4092 --reason "<one line: fresh-plane stamp + integer schema_version refusal>"`; `wikitoolkit ledger show issue:f249c19e8a4d` then reports it closed, resolved by `task:TASK-4092`.
- [ ] Existing store tests still pass (`test_store_meta.py`, `test_store_rebuild_index.py`, `test_store_attrs.py`, `test_sqlite_fts_external_content.py`).
- [ ] No new dependency; `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/store.py` clean.

---

## Validation Commands

Run from the feature worktree with `PYTHONPATH=packages/ai-parrot/src` (the shared venv is
editable-installed against the main checkout).

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_store_runtime_gate.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_store_meta.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_store_rebuild_index.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_store_attrs.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_sqlite_fts_external_content.py -q`

---

## Test Specification

See the CREATE block for `packages/ai-parrot/tests/knowledge/wiki/test_store_runtime_gate.py`
(`test_gate_blocks_older_runtime` per spec §4, read-only gate, write gate, migration stamp,
creation stamp, `test_newer_schema_version_refused` (integer comparison, left unchanged), same-schema
newer-release open and non-integer schema migrate *[rev 0.5 C24 / D8]*).

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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4092 parrot-installer verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state
11. **Close the ledger issue** this task fixes (rev 0.5 C24):
    `wikitoolkit ledger close issue:f249c19e8a4d --resolved-by task:TASK-4092 --reason "<one line>"`

---

## Completion Note

**Completed by**: agent:sdd-fix (Claude Opus 5), via `/sdd-fix issue:f249c19e8a4d`
**Date**: 2026-10-22
**Notes**: Implemented exactly as the blueprint fixes it, both `FILL IN` markers completed.

- `store.py`: `MIN_RUNTIME_KEY`, `_running_version()`, `WikiStoreVersionError(RuntimeError)`
  with the `newer_schema(...)` classmethod, and `SQLiteWikiStore._check_runtime_gate()`.
  The gate is called from all four connect sites — `_open` (after `_apply_pragmas`, before
  `_ensure_schema`), `_connect_immutable`, and both `_connect_readonly` rungs (each before
  `yielded = True`). `min_runtime_version` is stamped in the fresh-plane block of
  `_ensure_schema` (`INSERT OR IGNORE`) and in `_migrate`'s `if version_stale:` branch.
  `_migration_needed` was not touched; `rebuild_index`'s restamp was left alone and is
  covered by the gate instead.
- The gate compares `schema_version` as integers and fails open on a missing `meta` table,
  a missing row, or a non-integer value (warning + open, then stale/migrate as today).
  `min_runtime_version` is never compared.
- Tests: `packages/ai-parrot/tests/knowledge/wiki/test_store_runtime_gate.py`, 9 tests, all
  passing. The two `FILL IN` tests were written as bounded: `test_gate_blocks_read_only_store`
  (read-only store refused) and `test_gate_blocks_writes_before_any_write` (`set_meta` and
  `rebuild_index` both refused; `schema_version` still "99" and `k` still "v" afterwards —
  nothing written). `test_newer_schema_version_refused` also asserts the read-only refusal.
- Codebase Contract re-verified against dev `e01686b21` before writing code: every anchor
  and every blueprint occurrence count still matched exactly (`SCHEMA_VERSION = "3"`,
  `AttrsUnsupportedError`, the `_assert_writable` raise, the `_apply_pragmas` call, 1×
  12-space and 2× 16-space `_log_read_only_once()`, the `_ensure_schema` insert).
  `version.py:8` is still `__version__ = "1.2.3"`.
- Validation: the 5 Validation Commands pass (9 + 30 tests). Wider sweep:
  `packages/ai-parrot/tests/knowledge/wiki/` 1196 passed / 6 failed and
  `tests/knowledge/wiki/` 2079 passed / 11 skipped. The 6 failures are pre-existing and
  unrelated (arango backend dispatch, CLI surface golden, standup assets, backend parity) —
  confirmed by running those same 6 node ids in the main checkout on pristine `dev`, where
  they fail identically. `ruff check` clean; `black --line-length 120` applied.
- Worktree note: `feat-FEAT-633-parrot-installer` was a 570-commit-stale `dev` snapshot with
  zero feature commits (local `97e808e62`, remote `6059706c`, both already contained in
  `origin/dev`), so it was fast-forwarded to `origin/dev` before implementing — otherwise the
  branch diff would have read as a mass revert.

**Deviations from spec**: none
