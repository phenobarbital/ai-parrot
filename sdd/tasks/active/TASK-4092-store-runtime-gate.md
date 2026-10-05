# TASK-4092: Wiki store: min_runtime_version stamp + WikiStoreVersionError gate

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 items (a)(c)(d) — here (c) the stamp and (d) the gate; backup + lock are
TASK-4093. With a managed runtime (`~/.parrot/venv`) and project venvs coexisting, two
different ai-parrot versions can open the same `wiki.db`. `SQLiteWikiStore` already
auto-migrates silently on `schema_version` mismatch (`_maybe_migrate` → `_migrate`);
nothing ever refuses an open (spec §6 "Today a version mismatch is ALWAYS migrated
silently"). The owner's skew policy (spec §8 "Skew concurrency guard") is a **store-side
min-runtime gate**: migration stamps `min_runtime_version` into the existing `meta`
key/value table, and every connection — read-write AND read-only — checks it first; an
older runtime fails fast with `WikiStoreVersionError` naming both versions and the fix.

**Known limitation (document in the docstring)**: only runtimes that contain this task
honour the gate — a pre-FEAT-633 runtime ignores the row (spec §7 "Version-skew
auto-migration").

---

## Scope

- Add module constant `MIN_RUNTIME_KEY = "min_runtime_version"`.
- Add `WikiStoreVersionError(RuntimeError)` — NOT an `sqlite3.OperationalError` subclass
  (`_read` catches `OperationalError` to degrade to read-only, store.py:1233; the gate
  must never be swallowed by that ladder).
- Add module helpers `_running_version() -> str` (reads `parrot.version.__version__` at
  call time — the test seam) and `_release_tuple(version: str) -> tuple[int, ...]`
  (PEP 440 **release segment only**; `packaging` is not a core dependency).
- Add `SQLiteWikiStore._check_runtime_gate(conn)` and call it in `_open`,
  `_connect_immutable` and both rungs of `_connect_readonly`, BEFORE the connection is
  used/yielded.
- In `_migrate`, stamp `min_runtime_version = _running_version()` alongside the
  `schema_version` restamp.
- Tests in a new file.

**NOT in scope**: pre-migration backup/restore and the cross-process migration lock
(TASK-4093); stamping from `rebuild_index` (store.py:2620-2636 restamps `schema_version`
but is not a migration — leave it; it already goes through `_write` → `_open`, so it is
gated); `PRAGMA user_version` (spec: never introduced); other backends
(`InMemoryWikiStore`, Arango, Postgres).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` | MODIFY | Gate constant, error, helpers, check, stamp |
| `packages/ai-parrot/tests/knowledge/wiki/test_store_runtime_gate.py` | CREATE | Gate + stamp tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot import version as _parrot_version  # verified: packages/ai-parrot/src/parrot/version.py:8 (__version__ = "1.1.0"); parrot/__init__.py already imports .version → no cycle
from parrot.knowledge.wiki.store import SCHEMA_VERSION, SQLiteWikiStore  # verified: store.py:51,948
import aiosqlite  # verified: store.py:43
import sqlite3  # verified: store.py:33
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
SCHEMA_VERSION = "3"                                                        # line 51
class WikiStoreBusy(sqlite3.OperationalError):                              # line 284
class AttrsUnsupportedError(RuntimeError):                                  # line 429 — style precedent for the new error
class SQLiteWikiStore(BaseWikiStore):                                       # line 948
    def __init__(self, db_path, wiki_name="", *, read_only=False, sqlite_policy=None, persistent_writer=False)  # line 1000-1008
    def _assert_writable(self) -> None:                                     # line 1061 (raise at 1068)
    async def _apply_pragmas(self, conn, *, writable: bool) -> None:        # line 1074
    async def _open(self, *, writable: bool) -> AsyncIterator[aiosqlite.Connection]:  # line 1108; connect 1122; pragmas 1128; _ensure_schema 1130
    async def _ensure_schema(self, conn) -> None:                           # line 1133 (fresh plane: INSERT OR IGNORE schema_version 1156-1159)
    async def _maybe_migrate(self, conn) -> None:                           # line 1167
    async def _read(self):                                                  # line 1190; `except sqlite3.OperationalError` at 1233
    async def _connect_immutable(self):                                     # line 1301; connect 1311-1313; _log_read_only_once 1317
    async def _connect_readonly(self):                                      # line 1321; mode=ro rung 1348-1354; immutable rung 1383-1390
    async def _migration_needed(self, conn) -> tuple[list[...], bool]:      # line 1413 (reads schema_version 1437; stale check 1441)
    async def _migrate(self, conn) -> None:                                 # line 1444; restamp 1492-1496; commit 1497
    async def get_meta(self, key: str) -> Optional[str]:                    # line 2202
    async def set_meta(self, key: str, value: str) -> None:                 # line 2209
    async def rebuild_index(self) -> dict[str, Any]:                        # line 2620 (restamp 2631-2635 — NOT a migration)
WikiStore = SQLiteWikiStore                                                 # line 2662
```
- Foreign planes are opened `read_only=True` (`federation.py:297-302`); they go through
  `_connect_immutable` / `_connect_readonly` only (store.py:1203-1225) and never migrate.
- Tests run with `asyncio_mode = "auto"` (packages/ai-parrot/pyproject.toml:1034) — plain
  `async def test_…` (precedent: `tests/knowledge/wiki/test_store_meta.py`).

### Does NOT Exist
- ~~`MIN_RUNTIME_KEY`, `WikiStoreVersionError`, `_check_runtime_gate`, `_running_version`, `_release_tuple`~~ — added here.
- ~~`PRAGMA user_version`~~ anywhere in `knowledge/wiki/` — never introduce it.
- ~~`packaging` as a core ai-parrot dependency~~ — absent from `packages/ai-parrot/pyproject.toml`; do not import it.
- ~~any open-time version refusal today~~ — this task adds the first one.
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
# store.py:1437-1438 — reading one meta row
async with conn.execute("SELECT value FROM meta WHERE key = 'schema_version'") as cur:
    row = await cur.fetchone()
```

### Key Constraints
- Gate runs on EVERY connection (one indexed SELECT) — never latch it per instance: a newer
  runtime may migrate the plane while this instance is alive.
- A plane with no `meta` table yet (brand-new file, `_open` before `_ensure_schema`) or no
  `min_runtime_version` row (pre-FEAT-633 plane) opens normally.
- In `_open`, check AFTER `_apply_pragmas` (so `busy_timeout` covers the SELECT) and
  BEFORE `_ensure_schema` (so an older runtime writes nothing to a newer plane).
- Stamp only inside `_migrate`'s `if version_stale:` block — a plane whose schema did not
  change keeps accepting older runtimes. Because the gate already refused any runtime older
  than an existing stamp, writing the running version never lowers it.
- Unparsable stamp → log a warning and allow the open (the row is written only by this
  code; failing closed on garbage would brick a plane with no fix path).
- Error message must contain: the store path, the store's minimum, the running version,
  and the fix `parrot self update` (managed runtime) / `parrot self add --here` (project venv).

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:1107-1131, 1300-1395, 1444-1497`

---

## Implementation Blueprint

### Steps (in order)
1. Add the constant, helpers and error class — *why*: spec §3 M7 skeleton names are fixed.
2. Add `_check_runtime_gate` to `SQLiteWikiStore` — *why*: one implementation for all four connect sites.
3. Call it in `_open`, `_connect_immutable`, and both `_connect_readonly` rungs — *why*: spec §5 "read-only paths included".
4. Stamp in `_migrate` — *why*: spec §3 M7 (c).
5. Write tests — *why*: spec §4 `test_gate_blocks_older_runtime`.

### `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'SCHEMA_VERSION = "3"' packages/ai-parrot/src/parrot/knowledge/wiki/store.py)
# AFTER — insert below `SCHEMA_VERSION = "3"` (verified: store.py:51)

#: FEAT-633: lowest ai-parrot (wikitoolkit) version allowed to open a plane; a ``meta`` row
#: stamped by ``SQLiteWikiStore._migrate``. Only runtimes containing this gate honour it.
MIN_RUNTIME_KEY = "min_runtime_version"


def _running_version() -> str:
    """The running ai-parrot version, read at call time (tests patch ``parrot.version.__version__``)."""
    from parrot import version as _parrot_version  # stdlib-only module; parrot/__init__ already loaded it

    return _parrot_version.__version__


def _release_tuple(version: str) -> tuple[int, ...]:
    """PEP 440 release segment as ints, trailing zeros stripped ("1.2.0rc1" -> (1, 2)).

    Pre/post/dev/local segments are ignored on purpose: a release candidate compares equal
    to its final release.

    Raises:
        ValueError: no leading numeric release segment.
    """
    # FILL IN: regex r"^\s*[vV]?(\d+(?:\.\d+)*)" → ints → strip trailing zeros — bounded by
    # "release segment only; packaging is not a core dependency"
    raise NotImplementedError
```
```python
# occurrences: 1 (verified: grep -c 'class AttrsUnsupportedError(RuntimeError):' packages/ai-parrot/src/parrot/knowledge/wiki/store.py)
# AFTER — insert below the AttrsUnsupportedError class body (verified: store.py:429-430)


class WikiStoreVersionError(RuntimeError):
    """The plane's ``min_runtime_version`` exceeds the running ai-parrot version.

    Deliberately NOT a :class:`sqlite3.OperationalError`: the read ladder in
    ``SQLiteWikiStore._read`` degrades on OperationalError, and this must never degrade.
    """

    def __init__(self, db_path: Path, store_minimum: str, running: str) -> None:
        self.db_path = db_path
        self.store_minimum = store_minimum
        self.running = running
        super().__init__(
            f"wiki store {db_path} requires ai-parrot >= {store_minimum}, but this runtime is {running}. "
            "Upgrade: `parrot self update` (managed runtime) or `parrot self add --here` (project venv)."
        )
```
```python
# occurrences: 1 (verified: grep -c '            raise PermissionError(f"read-only wiki store: {self._db_path}")' packages/ai-parrot/src/parrot/knowledge/wiki/store.py)
# AFTER — insert below that line, i.e. after `_assert_writable` (verified: store.py:1068)

    async def _check_runtime_gate(self, conn: aiosqlite.Connection) -> None:
        """Refuse the plane when its ``min_runtime_version`` exceeds the running version.

        One indexed read per connection. A plane without a ``meta`` table (brand new) or
        without the row (pre-FEAT-633) passes.

        Raises:
            WikiStoreVersionError: the store requires a newer runtime.
        """
        try:
            async with conn.execute("SELECT value FROM meta WHERE key = ?", (MIN_RUNTIME_KEY,)) as cur:
                row = await cur.fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc):
                return
            raise
        if row is None:
            return
        running = _running_version()
        # FILL IN: parse both with _release_tuple; ValueError → self.logger.warning + return (fail open,
        # see Key Constraints); store tuple > running tuple → raise WikiStoreVersionError(self._db_path, row[0], running)
        raise NotImplementedError
```
```python
# occurrences: 1 (verified: grep -c '        await self._apply_pragmas(conn, writable=writable)' packages/ai-parrot/src/parrot/knowledge/wiki/store.py)
# AFTER — insert below that line in `_open` (verified: store.py:1128), BEFORE `if writable: await self._ensure_schema(conn)`
            await self._check_runtime_gate(conn)
```
```python
# occurrences: 1 (verified: grep -c '^            self._log_read_only_once()$' packages/ai-parrot/src/parrot/knowledge/wiki/store.py)
# AFTER — insert below the 12-space-indented `self._log_read_only_once()` in `_connect_immutable` (verified: store.py:1317)
            await self._check_runtime_gate(conn)
```
```python
# occurrences: 2 (verified: grep -c '^                self._log_read_only_once()$' packages/ai-parrot/src/parrot/knowledge/wiki/store.py)
# AFTER — insert below EACH of the two 16-space occurrences in `_connect_readonly`, disambiguated by context:
#   (1) store.py:1352, in the rung opened by
#       `async with aiosqlite.connect(f"{base}?mode=ro", uri=True, timeout=self._policy.busy_timeout_s) as conn:` (store.py:1348)
#   (2) store.py:1388, in the rung opened by
#       `f"{base}?mode=ro&immutable=1", uri=True, timeout=self._policy.busy_timeout_s` (16-space indent, store.py:1384)
# Both insertions go BEFORE `yielded = True` (store.py:1353 / 1389) so a gate error is raised, not swallowed.
                await self._check_runtime_gate(conn)
```
```python
# occurrences: 2 (verified: grep -c '                (SCHEMA_VERSION,),' packages/ai-parrot/src/parrot/knowledge/wiki/store.py)
# AFTER — the `_migrate` occurrence only (store.py:1492-1496), disambiguated by its context:
#             await conn.execute(
#                 "INSERT INTO meta (key, value) VALUES ('schema_version', ?)"
#                 " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
#                 (SCHEMA_VERSION,),
#             )
#         await conn.commit()          <- store.py:1497; the OTHER occurrence (store.py:2634) is rebuild_index — leave it
# Insert after the closing `            )` at store.py:1496, still inside `if version_stale:`
            await conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (MIN_RUNTIME_KEY, _running_version()),
            )
```
**Why**: the gate already refused any runtime older than an existing stamp, so an
unconditional upsert of the running version can never lower it.

### `packages/ai-parrot/tests/knowledge/wiki/test_store_runtime_gate.py` (CREATE)
```python
"""FEAT-633 M7 — min_runtime_version gate (TASK-4092)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from parrot.knowledge.wiki import store as store_mod
from parrot.knowledge.wiki.store import MIN_RUNTIME_KEY, SQLiteWikiStore, WikiStoreVersionError


async def _built_plane(tmp_path: Path) -> Path:
    db = tmp_path / "wiki.db"
    await SQLiteWikiStore(db, "t").set_meta("k", "v")  # builds schema
    return db


def _stamp(db: Path, key: str, value: str) -> None:
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


async def test_unstamped_plane_opens(tmp_path: Path) -> None:
    db = await _built_plane(tmp_path)
    assert await SQLiteWikiStore(db, "t").get_meta("k") == "v"


async def test_gate_blocks_older_runtime(tmp_path: Path) -> None:
    """Spec §4 — a higher stamp raises with both versions and the fix in the message."""
    db = await _built_plane(tmp_path)
    _stamp(db, MIN_RUNTIME_KEY, "99.0.0")
    with pytest.raises(WikiStoreVersionError) as info:
        await SQLiteWikiStore(db, "t").get_meta("k")
    message = str(info.value)
    assert "99.0.0" in message and store_mod._running_version() in message and "parrot self update" in message


async def test_gate_blocks_read_only_store(tmp_path: Path) -> None:
    # FILL IN: same stamp, SQLiteWikiStore(db, "t", read_only=True).get_meta → WikiStoreVersionError
    # (covers _connect_immutable / _connect_readonly) — bounded by spec §5 "read-only paths included"
    raise NotImplementedError


async def test_gate_blocks_writes_before_any_write(tmp_path: Path) -> None:
    # FILL IN: stamp 99.0.0; set_meta raises WikiStoreVersionError and the meta row "k" is unchanged — bounded by spec §3 M7 (d)
    raise NotImplementedError


async def test_migration_stamps_running_version(tmp_path: Path) -> None:
    """A stale schema_version migrates and stamps min_runtime_version = running version."""
    db = await _built_plane(tmp_path)
    _stamp(db, "schema_version", "2")
    await SQLiteWikiStore(db, "t").get_meta("k")  # first open migrates
    assert await SQLiteWikiStore(db, "t").get_meta(MIN_RUNTIME_KEY) == store_mod._running_version()


async def test_newer_runtime_opens_older_stamp(tmp_path: Path) -> None:
    # FILL IN: stamp "0.0.1"; opens fine — bounded by "only a higher minimum refuses"
    raise NotImplementedError


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("1.2.0", (1, 2)), ("1.2", (1, 2)), ("v1.10.3", (1, 10, 3)), ("1.2.0rc1", (1, 2)), ("2", (2,))],
)
def test_release_tuple(raw: str, expected: tuple[int, ...]) -> None:
    assert store_mod._release_tuple(raw) == expected


def test_release_tuple_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        store_mod._release_tuple("not-a-version")
```

### FILL IN checklist
- [ ] `store.py::_release_tuple` — regex + strip trailing zeros; bounded by "release segment only"
- [ ] `store.py::SQLiteWikiStore._check_runtime_gate` — compare + fail-open on garbage; bounded by Key Constraints
- [ ] `test_store_runtime_gate.py` — the three FILL IN tests; bounded by spec §5 / §3 M7 (d)

---

## Acceptance Criteria

- [ ] `MIN_RUNTIME_KEY`, `WikiStoreVersionError(RuntimeError)`, `_check_runtime_gate` exist with the names fixed by spec §3 M7.
- [ ] A plane stamped with a higher `min_runtime_version` raises `WikiStoreVersionError` on `_open` AND on the read-only connects, before any write (spec §5 "read-only paths included"; §4 `test_gate_blocks_older_runtime`).
- [ ] The message names the store minimum, the running version and the fix (`parrot self update` / `parrot self add --here`).
- [ ] `_migrate` stamps `min_runtime_version` alongside `schema_version`; unstamped (pre-FEAT-633) and brand-new planes open normally.
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
version parsing).

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

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
