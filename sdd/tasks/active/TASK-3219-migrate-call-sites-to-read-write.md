# TASK-3219: Migrate all 21 store call sites to _read/_write and remove _connect

**Feature**: FEAT-557 — wikitoolkit SQLite concurrency hardening
**Spec**: `sdd/specs/wikitoolkit-sqlite-optimizations.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3217, TASK-3218
**Assigned-to**: unassigned

---

## Context

Spec §2: "`_read()` is the only route for reads and cannot begin a write." TASK-3217 built
`_read`/`_write` but deliberately left every existing method still calling `_connect()`, so
that task stayed reviewable. This is the mechanical sweep that finishes the job: 21 call
sites move to the correct primitive, and `_connect()` — whose write-first behaviour is the
root cause the feature exists to fix — is deleted.

This task is almost entirely mechanical. The complete, verified mapping is given below;
do not re-derive it.

> ### ⚠️ PR #1381 (wiki FTS schema v3) HAS LANDED — contract re-verified
> The FTS hotfix merged to `main` and synced into `dev` (`2394f2d95` → `641b16278`)
> **while this task was being written**. Every line number below was re-verified against
> the post-merge tree on 2026-09-14. The good news: **the sweep is unaffected in shape** —
> still 21 `self._connect()` call sites, the same 6 writers and 15 readers, each writer
> still with exactly one `await conn.commit()`. Only the line numbers moved.
>
> Two consequences worth knowing:
> - `pages_fts` / `symbols_fts` are now trigger-maintained external-content tables, so
>   `_upsert_pages_conn` no longer issues manual `DELETE FROM pages_fts`. This does not
>   change the conversion — you are not touching those bodies.
> - Two readers (`search_fts` store.py:1724, `search_symbols_fts` store.py:1604) now call
>   `await self._uses_legacy_fts(conn, ...)` inside the block you are converting. That
>   helper is a pure read (`PRAGMA table_info`, store.py:1217), so `_read()` serves it
>   correctly — no special handling needed.

---

## Scope

- Convert the 6 writer methods from `async with self._connect() as conn:` to
  `async with self._write("<method_name>") as conn:` and DELETE their now-redundant
  `await conn.commit()` (the `_write` context manager owns the commit).
- Convert the 15 reader methods to `async with self._read() as conn:`.
- Delete `_connect()` (store.py:887-976) once nothing references it.
- Keep `_connect_readonly`, `_connect_immutable`, `_sidecars_quiescent`,
  `_log_read_only_once` — `_read` still uses the ladder.
- Move the first-time schema-replay block (store.py:942-964) out of the deleted `_connect`
  into a place `_write` and `_read` both reach.

**NOT in scope**: any behaviour change to the methods themselves; `checkpoint()`
(TASK-3220); anything outside `store.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` | MODIFY | 21 call-site conversions; remove `_connect`; rehome schema replay |

---

## Codebase Contract (Anti-Hallucination)

### The complete call-site map — VERIFIED, do not re-derive

**Writers** — 6 methods. Each already calls `self._assert_writable()` first and has exactly
one `await conn.commit()` inside the `with` body. Convert to `_write("<name>")` and DELETE
the `commit()` line.

| Method | `def` line | `self._connect()` line | `await conn.commit()` line |
|---|---|---|---|
| `upsert_pages` | 1288 | **1303** | 1305 |
| `add_edges` | 1308 | **1325** | 1327 |
| `replace_source_slice` | 1330 | **1362** | 1404 |
| `delete_page` | 1418 | **1431** | 1439 |
| `upsert_embedding` | 1442 | **1459** | 1464 |
| `upsert_symbols` | 1466 | **1517** | 1535 |

**Readers** — 15 methods. No `_assert_writable`, no `commit()`. Convert to `_read()`.

| Method | `def` line | `self._connect()` line |
|---|---|---|
| `symbols_for` | 1538 | **1547** |
| `find_symbols` | 1554 | **1600** |
| `search_symbols_fts` | 1604 | **1617** |
| `page_hashes` | 1629 | **1644** |
| `get_page` | 1657 | **1675** |
| `list_pages` | 1686 | **1720** |
| `search_fts` | 1724 | **1750** |
| `search_vector` | 1775 | **1792** |
| `neighbors` | 1817 | **1841** |
| `dump_pages` | 1860 | **1866** |
| `dump_edges` | 1874 | **1876** |
| `stats` | 1880 | **1887** |
| `orphan_sources` | 1908 | **1910** |
| `broken_edges` | 1918 | **1920** |
| `missing_bodies` | 1928 | **1930** |

Totals: 21 `self._connect()` call sites, 9 `await conn.commit()` in the file — 6 in the
writers above, plus **store.py:964** (inside `_connect`'s schema replay, removed with it),
**store.py:1133** (inside `_migrate`) and **store.py:1185** (inside `_migrate_fts`). The
last two are owned by TASK-3218 / PR #1381 — leave both alone.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
@asynccontextmanager                                                       # 819
async def _connect(self) -> AsyncIterator[aiosqlite.Connection]:           # 820  <- DELETE (through 908)
def _sidecars_quiescent(self) -> bool:                                     # 910  <- KEEP
async def _connect_immutable(self) -> AsyncIterator[aiosqlite.Connection]: # 933  <- KEEP
async def _connect_readonly(self) -> AsyncIterator[aiosqlite.Connection]:  # 951  <- KEEP
def _log_read_only_once(self) -> None:                                     # 1025 <- KEEP
```

The first-time schema-replay block to rehome — **store.py:945-964**, verbatim:

```python
                cur = await conn.execute(
                    "SELECT count(*) FROM sqlite_master" f" WHERE type = 'table' AND name IN ({placeholders})",
                    sorted(_SCHEMA_TABLES),
                )
                if (await cur.fetchone())[0] < len(_SCHEMA_TABLES):
                    # Serialize first-time init across concurrent tasks
                    # of this instance; the DDL is idempotent, so the
                    # lock only avoids spurious cross-task lock errors.
                    async with self._init_lock:
                        await conn.executescript(WIKI_SCHEMA_SQL)
                        await conn.execute(
                            "INSERT OR IGNORE INTO meta (key, value)" " VALUES (?, ?)",
                            ("schema_version", SCHEMA_VERSION),
                        )
                        if self._wiki_name:
                            await conn.execute(
                                "INSERT OR IGNORE INTO meta (key, value)" " VALUES (?, ?)",
                                ("wiki_name", self._wiki_name),
                            )
                        await conn.commit()
```
with `placeholders = ", ".join("?" * len(_SCHEMA_TABLES))` from store.py:940.

### Does NOT Exist

- ~~a writer method that commits twice, or a reader that commits~~ — verified: exactly one
  `commit()` per writer, zero in the 15 readers. If you find another, STOP and report.
- ~~`replace_source_slice` being a reader~~ — it IS a writer (`_assert_writable` at 1205,
  `commit` at 1260, `self.logger.debug` at 1262).
- ~~`_migrate`'s `commit()` at store.py:1133 being one of the 6~~ — it is not; TASK-3218
  owns it. Do not touch it.
- ~~`BaseWikiStore._connect`~~ — the ABC has no such method; deleting
  `SQLiteWikiStore._connect` breaks no contract. Verified: `BaseWikiStore` (line 478) has
  no `__init__` and no connection methods.

---

## Implementation Blueprint

### Steps (in order)
1. Convert the 15 readers FIRST — *why*: they are the pure-mechanical half with no commit
   removal, so any test failure after this step isolates to the read path.
2. Convert the 6 writers, deleting each `await conn.commit()` in the same edit — *why*:
   leaving the commit in would COMMIT the `BEGIN IMMEDIATE` transaction early, and
   `_write`'s own trailing `COMMIT` would then fail with "no transaction is active".
3. Pass the method's own name as the `operation` argument — *why*: that string is what
   `WikiStoreBusy` reports to the user (AC-3); a generic `"write"` makes the error useless.
4. Rehome the schema replay into `_open(writable=True)` — *why*: `_connect` is being
   deleted but a brand-new plane still needs its schema before the first read or write;
   `_open` is the one place both `_read` and `_write` pass through.
5. Delete `_connect` LAST, after `grep -n 'self\._connect()' store.py` returns nothing —
   *why*: deleting it while a call site remains turns a mechanical sweep into a runtime
   AttributeError in whichever method you missed.
6. Run the full wiki suite — *why*: 21 conversions is exactly the size where one missed
   `commit()` hides until an integration test.

### `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` (MODIFY — readers, ×15)

```python
# occurrences: 21 total for `async with self._connect() as conn:` — NOT unique.
# FILL IN: disambiguate every edit by the enclosing `async def` line from the reader
# table above (e.g. anchor on `    async def get_page(self, concept_id: str,` at
# store.py:1657, then change the `async with` at 1533 inside it). Apply to all 15
# readers. The change is identical in each:
#   -        async with self._connect() as conn:
#   +        async with self._read() as conn:
```
**Why**: `_read` never migrates and never issues a write pragma, so after this sweep a read
on a current plane takes no writer lock — AC-4. The indentation is 8 spaces in every reader
(all are inside a method body, none inside a further block).

### `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` (MODIFY — writers, ×6)

```python
# occurrences: 21 total — NOT unique. Disambiguate by the enclosing `async def` from the
# writer table above. For EACH of the 6 writers make BOTH edits together:
#
#   -        async with self._connect() as conn:
#   +        async with self._write("<method_name>") as conn:
#
#   -            await conn.commit()          # delete this line entirely
#
# Example, `upsert_pages` (def at store.py:1288, connect at 1149, commit at 1151) —
# the body becomes:
#
#         self._assert_writable()
#         if not pages:
#             return 0
#         async with self._write("upsert_pages") as conn:
#             await self._upsert_pages_conn(conn, pages)
#         return len(pages)
#
# FILL IN: apply the same two-part edit to add_edges (1171/1173),
# replace_source_slice (1208/1260), delete_page (1287/1296),
# upsert_embedding (1316/1321) and upsert_symbols (1371/1397) — bounded by the
# writer table above; the operation string MUST be the method's own name (AC-3).
```
**Why**: `_write` owns the transaction end-to-end, so a leftover `await conn.commit()`
inside the body would close the `BEGIN IMMEDIATE` transaction early and make `_write`'s
trailing `COMMIT` raise. Keep `self._assert_writable()` where it is even though `_write`
also calls it — it gives the caller a `PermissionError` before any connection is opened,
which existing tests rely on.

### `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` (MODIFY — rehome schema replay)

```python
# occurrences: 1 (verified: grep -c 'await self._apply_pragmas(conn, writable=writable)' packages/ai-parrot/src/parrot/knowledge/wiki/store.py)
# AFTER — insert below `            await self._apply_pragmas(conn, writable=writable)`
#         inside `_open` (added by TASK-3217), before its `yield conn`:
            if writable:
                await self._ensure_schema(conn)
```

```python
# Add the helper next to `_open`:

    async def _ensure_schema(self, conn: aiosqlite.Connection) -> None:
        """Replay the schema when a cheap presence probe shows it missing.

        A new plane, or one externally replaced, has none of the eight
        tables in ``_SCHEMA_TABLES``. The probe is a pure read, so an
        already-built plane pays only one SELECT here. The DDL is
        idempotent; ``self._init_lock`` only prevents concurrent tasks of
        this instance from racing into spurious lock errors.

        Args:
            conn: An open, write-capable connection.
        """
        # FILL IN: move the block verbatim from the deleted `_connect`
        # (store.py:940-964 — `placeholders`, the sqlite_master count probe,
        # the `_init_lock`-guarded executescript, the two INSERT OR IGNORE
        # statements, the commit) — bounded by: it must stay a pure read when
        # all 8 tables are already present (AC-4), and the wiki_name insert is
        # conditional on `self._wiki_name`.
        raise NotImplementedError
```
**Why**: the probe must stay in the write-capable path only. On a read-only store `_read`
short-circuits into the ladder before `_open` is reached, so a foreign plane is still never
touched — which is what `TestExplicitReadOnlyMode` asserts.

### `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` (MODIFY — delete `_connect`)

```python
# occurrences: 1 (verified: grep -c '    async def _connect(self)' packages/ai-parrot/src/parrot/knowledge/wiki/store.py)
# DELETE lines 819-908 inclusive: the `@asynccontextmanager` decorator, `async def
# _connect(self)`, its docstring, and its whole body through the final
# `        async with self._connect_readonly() as conn:` / `            yield conn`.
# Stop at `    def _sidecars_quiescent(self) -> bool:` (store.py:978) — KEEP that and
# everything after it.
# Precondition: `grep -n 'self\._connect()' store.py` must return ZERO lines first.
```
**Why**: `_connect`'s write-first path — schema probe plus unconditional `_migrate` on
every connection, including for pure readers — is the root cause FEAT-557 exists to remove.
Leaving it as dead code invites a future call site to reintroduce the bug.

### FILL IN checklist
- [ ] 15 reader conversions to `_read()`; disambiguate each by its enclosing `async def`.
- [ ] 6 writer conversions to `_write("<name>")` + delete each `await conn.commit()`.
- [ ] `_ensure_schema` body moved verbatim from `_connect` (store.py:940-964).
- [ ] `_connect` deleted (store.py:887-976) after the grep returns zero.

---

## Acceptance Criteria

- [ ] `grep -n 'self\._connect()' packages/ai-parrot/src/parrot/knowledge/wiki/store.py`
      returns nothing.
- [ ] `grep -n 'async def _connect(self)' ...store.py` returns nothing.
- [ ] `_connect_readonly`, `_connect_immutable`, `_sidecars_quiescent` and
      `_log_read_only_once` all still exist.
- [ ] Exactly 6 `self._write(` call sites, each with the method's own name; exactly 15
      `self._read()` call sites.
- [ ] `await conn.commit()` remains only inside `_migrate` and `_ensure_schema`.
- [ ] A brand-new plane still builds its schema on first use.
- [ ] Full wiki suite green: `pytest tests/knowledge/wiki/ -q`
- [ ] `pytest tests/knowledge/wiki/test_store.py -v` — including `TestReadOnlyFallback`,
      `TestExplicitReadOnlyMode`, `TestReadOnlyConcurrencySafety`.
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/store.py`

---

## Test Specification

No new tests. This task's proof is that the **existing** suite stays green while
`_connect` disappears — `tests/knowledge/wiki/test_store.py` (664 lines, 12 test classes)
plus `test_store_migration_v2.py`, `test_search.py`, `test_symbols.py`, `test_toolkit.py`.
If a test needs changing to pass, STOP: that is a behaviour change this task forbids.

---

## Agent Instructions

1. **Read the spec** — §2 Overview, §3 Module 1.
2. **Check dependencies** — TASK-3217 and TASK-3218 both completed; `_read`, `_write`,
   `_open`, `_apply_pragmas` and the read-first `_migrate` must all exist.
3. **Verify the Codebase Contract** — re-run the call-site map before editing:
   `awk 'NR>=1130 && NR<=1800 { if ($0 ~ /^    async def /) n=$0; if ($0 ~ /self\._connect\(\)/) print NR"\t"n }' packages/ai-parrot/src/parrot/knowledge/wiki/store.py`
   It must print 21 rows matching the tables above. If it does not, update this contract
   FIRST.
4. **Implement** in the step order given — readers, writers, rehome, delete.
5. **Verify** every acceptance criterion.
6. **Move this file** to `sdd/tasks/completed/`; update the per-spec index; fill the note.

---

## Completion Note

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
