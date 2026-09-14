# TASK-3220: Non-fatal WAL checkpoint on SQLiteWikiStore

**Feature**: FEAT-557 — wikitoolkit SQLite concurrency hardening
**Spec**: `sdd/specs/wikitoolkit-sqlite-optimizations.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3217
**Assigned-to**: unassigned

---

## Context

Spec §2 and §3 Module 1. After a long `build` or `ingest`, the WAL can be large. A
checkpoint folds it back into the main database file and lets `journal_size_limit` cap the
retained WAL. `TRUNCATE` is the thorough mode, but a single live reader — another agent,
an MCP server holding a snapshot — can block it indefinitely.

The spec is emphatic that this is *observable maintenance, never a failure*: "never turns
an otherwise successful long write into a CLI failure". So `checkpoint()` observes whether
truncation was blocked, falls back to `PASSIVE`, logs the outcome, and returns a report.

`checkpoint()` is deliberately concrete to `SQLiteWikiStore` and is **not** added to
`BaseWikiStore` — adding it to the abstract contract would force the memory, ArangoDB and
Postgres backends to implement SQLite-only behaviour.

---

## Scope

- Add `async def checkpoint(self, truncate: bool = True) -> dict[str, int | bool]` to
  `SQLiteWikiStore`.
- Run `PRAGMA wal_checkpoint(TRUNCATE)`, detect a reader-blocked result, fall back to
  `PRAGMA wal_checkpoint(PASSIVE)`.
- Never raise for a blocked or partial checkpoint; log and report instead.
- Return a report dict the CLI (TASK-3224) and `status` (TASK-3225) can render.
- No-op safely on a read-only store.

**NOT in scope**: calling `checkpoint()` from the CLI (TASK-3224); the `status` sqlite
block (TASK-3225); adding anything to `BaseWikiStore`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` | MODIFY | Add `checkpoint()` to `SQLiteWikiStore` |
| `tests/knowledge/wiki/test_store_concurrency.py` | MODIFY | Checkpoint tests incl. the reader-blocked fallback |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

No new imports.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
class SQLiteWikiStore(BaseWikiStore):                             # line 774
    def _assert_writable(self) -> None:                           # line 874  (raises PermissionError)
    @property
    def read_only(self) -> bool:                                  # line 870
    self.logger                                                   # assigned at line 794
    self._policy: SQLitePragmaPolicy                              # added by TASK-3216/3217
    async def stats(self) -> dict[str, Any]:                      # line 1880  (last read method; anchor region)
```

From TASK-3217:
```python
@asynccontextmanager
async def _open(self, *, writable: bool) -> AsyncIterator[aiosqlite.Connection]:
```

### SQLite semantics you must rely on — verified, not assumed

`PRAGMA wal_checkpoint(<MODE>)` returns exactly **one row of three integers**:

| Column | Meaning |
|---|---|
| `busy` | `1` when the checkpoint could not complete because of a competing reader/writer; `0` otherwise |
| `log` | Pages in the WAL after the call (`-1` if WAL is not in use) |
| `checkpointed` | Pages successfully moved into the database (`-1` if WAL is not in use) |

`busy = 1` is the reader-blocked signal. It is a normal RESULT ROW, **not** an exception —
so "detect blocked truncation" means reading column 0, not catching `sqlite3.OperationalError`.

### Does NOT Exist

- ~~`BaseWikiStore.checkpoint`~~ — and this task must NOT add it. Verified: the only
  occurrence of the string `checkpoint` in `store.py` today is prose in the
  `_connect_readonly` docstring at **line 958**. There is no code.
- ~~`aiosqlite.Connection.wal_checkpoint()`~~ — no such driver method; issue the PRAGMA
  through `conn.execute`.
- ~~`PRAGMA wal_checkpoint` raising on a blocked checkpoint~~ — it does not; it returns
  `busy = 1`. Code that only wraps it in `try/except` will silently believe every
  checkpoint succeeded.
- ~~`journal_size_limit` shrinking the WAL while a reader snapshot is open~~ — spec §7:
  it constrains retained WAL size *after a successful checkpoint* only.

---

## Implementation Blueprint

### Steps (in order)
1. Return early on a read-only store — *why*: a checkpoint is a write on the WAL; a
   foreign, read-only plane must never be touched (AC-4 and FEAT-450's guarantee).
2. Read `busy` from the returned row rather than catching an exception — *why*: see the
   semantics table; a blocked TRUNCATE is a result row, and treating it as an exception
   means never detecting it.
3. Fall back to `PASSIVE` only when TRUNCATE reported `busy` — *why*: `PASSIVE` always
   succeeds without blocking and still reclaims what it can, so a busy plane still gets
   partial maintenance (spec §2).
4. Log at `info` on success and `warning` on a blocked truncation — *why*: spec calls this
   "observable maintenance"; the operator needs to see it without the build failing.
5. Catch `sqlite3.OperationalError` around the whole thing and report `ok=False` — *why*:
   AC-7. A genuinely broken checkpoint still must not turn a successful build into a
   failure.
6. Return a plain `dict` — *why*: TASK-3224 echoes it and TASK-3225 folds it into the
   `status` payload, which is JSON-serialized.

### `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c '    async def stats(self) -> dict\[str, Any\]:' packages/ai-parrot/src/parrot/knowledge/wiki/store.py)
# AFTER — append this method to `SQLiteWikiStore`, below the read methods. Anchor on
# `    async def stats(self) -> dict[str, Any]:` (verified: store.py:1880) and insert
# after the END of that method's body (it ends just before `    async def
# orphan_sources(self) -> list[str]:` at store.py:1908).

    async def checkpoint(self, truncate: bool = True) -> dict[str, int | bool]:
        """Fold the WAL back into the database; never raise for live readers.

        A single live reader can block ``TRUNCATE`` indefinitely. That is
        normal, observable maintenance — not an error — so this method
        falls back to ``PASSIVE``, logs the outcome, and reports it. It
        must never turn an otherwise successful build or ingest into a
        failure (AC-7).

        Args:
            truncate: Attempt ``TRUNCATE`` first. When False, only
                ``PASSIVE`` is run.

        Returns:
            A report with keys ``ok`` (the checkpoint ran at all),
            ``mode`` (the mode that actually took effect), ``busy``
            (truncation was blocked by a reader), ``log`` (pages left in
            the WAL) and ``checkpointed`` (pages moved).
        """
        if self._read_only:
            self.logger.debug("checkpoint skipped: %s is read-only", self._db_path)
            return {"ok": False, "mode": "skipped", "busy": False, "log": -1, "checkpointed": -1}
        try:
            async with self._open(writable=True) as conn:
                mode = "TRUNCATE" if truncate else "PASSIVE"
                async with conn.execute(f"PRAGMA wal_checkpoint({mode})") as cur:
                    row = await cur.fetchone()
                busy, log, checkpointed = (int(row[0]), int(row[1]), int(row[2]))
                if busy and truncate:
                    # A reader holds a snapshot. PASSIVE cannot block and
                    # still reclaims what it can.
                    self.logger.warning(
                        "WAL TRUNCATE on %s was blocked by a live reader —"
                        " falling back to PASSIVE (%d page(s) still in WAL)",
                        self._db_path,
                        log,
                    )
                    # FILL IN: run `PRAGMA wal_checkpoint(PASSIVE)`, re-read the
                    # three columns, and set mode to "PASSIVE" — bounded by AC-7
                    # (never raise) and by the semantics table in the Codebase
                    # Contract (PASSIVE reports busy=0 in practice, but read the
                    # row rather than assuming it).
                    raise NotImplementedError
                self.logger.info(
                    "WAL checkpoint(%s) on %s: %d page(s) checkpointed, %d left",
                    mode,
                    self._db_path,
                    checkpointed,
                    log,
                )
                return {
                    "ok": True,
                    "mode": mode,
                    "busy": bool(busy),
                    "log": log,
                    "checkpointed": checkpointed,
                }
        except sqlite3.OperationalError as exc:
            # AC-7: maintenance failure must never fail the caller's build.
            self.logger.warning("WAL checkpoint on %s failed: %s", self._db_path, exc)
            return {"ok": False, "mode": "failed", "busy": False, "log": -1, "checkpointed": -1}
```
**Why this shape**: reading `busy` from the result row is the ONLY correct way to detect a
blocked truncation — the PRAGMA does not raise. The method returns a dict rather than
raising or returning a bool because TASK-3224 echoes the outcome to the operator and
TASK-3225 may surface it in `status`; both need the page counts. `_read_only` short-circuits
before `_open` so a foreign plane gets no write-capable connection at all. Do NOT add this
method to `BaseWikiStore` — spec §2 is explicit that it stays concrete.

### `tests/knowledge/wiki/test_store_concurrency.py` (MODIFY)

```python
# AFTER — append a new class at the end of the file.

class TestCheckpoint:
    async def test_checkpoint_reports_success(self, store: SQLiteWikiStore) -> None:
        """A quiet plane checkpoints in TRUNCATE mode."""
        # FILL IN: write some pages, call `await store.checkpoint()`, assert
        # ok is True, mode == "TRUNCATE" and busy is False — bounded by AC-7.

    async def test_reader_blocked_truncate_falls_back_to_passive(self, store: SQLiteWikiStore) -> None:
        """A live reader forces PASSIVE and never raises (AC-7)."""
        # FILL IN: hold an open stdlib sqlite3 read transaction (BEGIN; SELECT ...)
        # against the same file so TRUNCATE reports busy=1, then assert
        # checkpoint() returns without raising and mode == "PASSIVE" —
        # bounded by AC-7 and spec §7 ("a reader can prevent TRUNCATE even after
        # writer success"). Keep the reader connection open for the whole call.

    async def test_read_only_store_skips(self, tmp_path: Path) -> None:
        """A read-only store never writes, so it never checkpoints."""
        # FILL IN: bounded by AC-4 / FEAT-450 (a foreign plane is never mutated).

    async def test_checkpoint_is_not_on_the_base_contract(self) -> None:
        """`checkpoint` stays concrete to SQLiteWikiStore (spec §2)."""
        from parrot.knowledge.wiki.store import BaseWikiStore

        assert not hasattr(BaseWikiStore, "checkpoint")
```

### FILL IN checklist
- [ ] `checkpoint()` PASSIVE fallback branch; bounded by AC-7 and the semantics table.
- [ ] `test_checkpoint_reports_success`; bounded by AC-7.
- [ ] `test_reader_blocked_truncate_falls_back_to_passive`; bounded by AC-7 / spec §7.
- [ ] `test_read_only_store_skips`; bounded by AC-4.

---

## Acceptance Criteria

- [ ] `SQLiteWikiStore.checkpoint()` exists; `BaseWikiStore.checkpoint` does NOT.
- [ ] On a quiet plane it returns `ok=True, mode="TRUNCATE"`.
- [ ] With a live reader holding a snapshot it returns without raising, having fallen back
      to `PASSIVE`, and logs a warning.
- [ ] On a read-only store it is a no-op and issues no write.
- [ ] A `sqlite3.OperationalError` anywhere inside is caught and reported as
      `ok=False`, never propagated.
- [ ] Tests pass: `pytest tests/knowledge/wiki/test_store_concurrency.py -v`
- [ ] No regression: `pytest tests/knowledge/wiki/test_store.py -q`
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/store.py`

---

## Test Specification

See the blueprint. The reader-blocked test is the important one — it is the only place the
`busy` column path is exercised, and it is what proves a build cannot be failed by an
unlucky concurrent reader.

---

## Agent Instructions

1. **Read the spec** — §2 (the `checkpoint` paragraph), §3 Module 1, §7 Gotchas, AC-7.
2. **Check dependencies** — TASK-3217 completed; `_open` must exist.
3. **Verify the Codebase Contract** — confirm `stats` is still at store.py:1880 and that
   `checkpoint` still appears only as prose at store.py:1026.
4. **Implement** from the blueprint; complete every `FILL IN`.
5. **Verify** every acceptance criterion.
6. **Move this file** to `sdd/tasks/completed/`; update the per-spec index; fill the note.

---

## Completion Note

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
