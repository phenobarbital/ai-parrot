# TASK-4380: Ledger hard cut — LedgerTxn / LedgerReader protocols

**Feature**: FEAT-670 — HelixDB graph provider
**Spec**: `sdd/specs/helixdb-provider.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 (G3, AC5, resolved Q5 "hard cut, no shim"; design-research S2): `LedgerStore.ledger_transaction()`
today yields a raw `aiosqlite.Connection` and `LedgerIndex` / `SDDGraphIngest` / `LedgerService` issue
SQL on it (or on `store._read()`). Before a HelixDB ledger (TASK-4381) can exist, the ledger must talk to
its store through a backend-neutral **`LedgerTxn`** (writes, plus the reads a write transaction needs) and
**`LedgerReader`** (read-only). This task defines both protocols, implements them for SQLite, and rewrites
every call site. It is pure refactor for SQLite: behaviour, `_write(operation)` busy-timeout semantics and
`WikiStoreBusy` propagation must be identical (`/sdd-done` and `/sdd-fix` depend on the ledger).

---

## Scope

- In `wiki/ledger/store.py`: add `LedgerTxn` and `LedgerReader` Protocols, `_SQLiteLedgerTxn`,
  `_SQLiteLedgerReader`; change `ledger_transaction()` to yield a `LedgerTxn`; add `ledger_read()`.
  Keep `upsert_pages_in` / `add_edges_in` (now used only by `_SQLiteLedgerTxn`) and `read_cursor`.
- In `wiki/ledger/index.py`: retype every `conn: "aiosqlite.Connection"` to `txn: "LedgerTxn"`; replace
  the raw SQL (`_read_issue`, `_write_cursor`, `_rebuild_locked_with_cursor` DELETEs, `compact` SELECT)
  with `LedgerTxn` calls; `self.store.upsert_pages_in(conn, …)` / `add_edges_in(conn, …)` → `txn.upsert_pages(…)` /
  `txn.add_edges(…)`. Remove the `aiosqlite` TYPE_CHECKING import.
- In `wiki/ledger/sdd_ingest.py`: the two transaction blocks call `txn.upsert_pages` / `txn.add_edges`.
- In `wiki/ledger/service.py`: the three `async with self.store._read() as conn:` blocks become
  `async with self.store.ledger_read() as reader:`; update the module docstring (no `_read()` mention).
- Update the existing root ledger tests that poke the yielded connection with SQL.
- Add `packages/ai-parrot/tests/knowledge/wiki/test_ledger_txn.py`.

**NOT in scope**: `HelixLedgerStore` and `LedgerService` backend dispatch (TASK-4381); `audit()`'s
`self.store.sqlite_settings()` (stays — SQLite store); `LedgerLog`; `federation.py`'s own `store._read()`
(not ledger).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py` | MODIFY | Protocols + SQLite implementations; `ledger_transaction` yields `LedgerTxn`; `ledger_read()` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py` | MODIFY | Retype to `LedgerTxn`; no raw SQL |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_ingest.py` | MODIFY | Two blocks use `txn.upsert_pages` / `txn.add_edges` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py` | MODIFY | Three reads via `ledger_read()`; docstring |
| `tests/knowledge/wiki/test_ledger_store.py` | MODIFY | Rewrite conn-SQL tests against `LedgerTxn` / `LedgerReader` |
| `tests/knowledge/wiki/test_ledger_index.py` | MODIFY | `:135` corrupt-cursor via `txn.set_state`; `:172` edge check via `store.neighbors` |
| `tests/knowledge/wiki/test_ledger_integration.py` | MODIFY | `:84` / `:123` raw SQL → `ledger_read()` / `store.neighbors` |
| `tests/knowledge/wiki/test_ledger_sdd_ingest.py` | MODIFY | Mocks assert `txn.upsert_pages` / `txn.add_edges` instead of `store.upsert_pages_in` / `add_edges_in` |
| `packages/ai-parrot/tests/knowledge/wiki/test_ledger_txn.py` | CREATE | Hard-cut + protocol tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.ledger.store import LedgerStore  # verified: wiki/ledger/store.py:24
from parrot.knowledge.wiki.ledger.index import LedgerIndex, _decode_issue_body  # verified: wiki/ledger/index.py:86, :62
from parrot.knowledge.wiki.ledger.service import LedgerService  # verified: wiki/ledger/service.py:127
from parrot.knowledge.wiki.ledger.sdd_ingest import SDDGraphIngest  # verified: imported by tests/knowledge/wiki/test_ledger_integration.py
from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiPageRecord, WikiStoreBusy  # verified: wiki/store.py:1092, :433, :284
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py
class LedgerStore(SQLiteWikiStore):                                                              # line 24
    async def ledger_transaction(self, operation: str) -> AsyncIterator[aiosqlite.Connection]    # line 54 (@asynccontextmanager :53)
        # body: async with self._write(operation) as conn: CREATE TABLE IF NOT EXISTS ledger_state(key PK, value) ; yield conn
    async def read_cursor(self) -> tuple[int, str | None]                                        # line 75 (via self._read())
    async def upsert_pages_in(self, conn: aiosqlite.Connection, pages: list[WikiPageRecord]) -> None  # line 107
    async def add_edges_in(self, conn: aiosqlite.Connection, edges: list[tuple]) -> None          # line 116
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
class SQLiteWikiStore:  _read() :1334 (asynccontextmanager → aiosqlite.Connection, row_factory Row) ; _write(operation) :1384
                        neighbors(concept_id, rel=None, direction="both") :2552
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py — conn uses (all to be rewritten):
#   apply_event :103 ; _read_issue :126 (SELECT body FROM pages WHERE concept_id = ?) ; _write_issue :134 (upsert_pages_in :157)
#   _apply_issue_* :159-245 (add_edges_in) ; _write_cursor :252 (staticmethod; INSERT OR REPLACE INTO ledger_state ×2)
#   sync(conn=None) :263 ; ledger_transaction("ledger.sync") :276 ; _sync_locked :280 ; _apply_from :293
#   rebuild :353 ("ledger.rebuild" :359) ; _rebuild_locked :362 ; _rebuild_locked_with_cursor :367 (DELETE pages/edges/ledger_state :375-377)
#   claim_issue ("ledger.claim" :440) ; close_issue ("ledger.close" :477) ; unclaim_issue ("ledger.unclaim" :511)
#   compact ("ledger.compact" :548; SELECT concept_id, body, updated_at FROM pages WHERE category = 'issue' :549)
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_ingest.py — :99-102 and :195-198
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py — _all_issues :205 (_read :207, SELECT concept_id, body
#   … category='issue') ; _issue_state :336 (_read :338) ; audit :502 (_read :513, COUNT dangling edges excluding sym:/file:)
```

### Verified anchors (MODIFY)
| File | Anchor (verbatim) | `grep -c -F` |
|---|---|---|
| `ledger/store.py` | `    async def ledger_transaction(self, operation: str) -> AsyncIterator[aiosqlite.Connection]:` | 1 |
| `ledger/index.py` | `async def apply_event(self, event: LedgerEvent, conn: "aiosqlite.Connection") -> None:` | 1 |
| `ledger/index.py` | `async def _read_issue(self, conn: "aiosqlite.Connection", issue_id: str) -> dict[str, Any] \| None:` | 1 |
| `ledger/index.py` | `async def _write_cursor(conn: "aiosqlite.Connection", line_start: int, event_id: str) -> None:` | 1 |
| `ledger/index.py` | `await conn.execute("DELETE FROM pages")` | 1 |
| `ledger/index.py` | `async with conn.execute("SELECT concept_id, body, updated_at FROM pages WHERE category = 'issue'") as cur:` | 1 |
| `ledger/index.py` | `"aiosqlite.Connection"` (all retyped) | 14 |
| `ledger/index.py` | each of `"ledger.sync") as new_conn:` / `"ledger.rebuild") as conn:` / `"ledger.claim") as conn:` / `"ledger.close") as conn:` / `"ledger.unclaim") as conn:` / `"ledger.compact") as conn:` | 1 each |
| `ledger/sdd_ingest.py` | `as conn:` (the two transaction blocks, `"ledger.ingest.specs"` :99 / `"ledger.ingest.tasks"` :195) | 2 |
| `ledger/service.py` | `        async with self.store._read() as conn:` (lines 207, 338, 513) | 3 — disambiguate by the following SELECT line |

### Does NOT Exist
- ~~`LedgerTxn`, `LedgerReader`, `ledger_read()`, `_SQLiteLedgerTxn`~~ — created here.
- ~~`LedgerStore.get_state()`~~ — not on dev; cursor reads stay in `read_cursor()`.
- ~~A compatibility shim yielding the connection~~ — forbidden (hard cut, Q5).
- ~~`tests/knowledge/wiki/ledger/`~~ (either tree) — no such directory; ledger tests are flat files (root `tests/knowledge/wiki/test_ledger_*.py`, package `packages/ai-parrot/tests/knowledge/wiki/test_ledger_*.py`). The plan's `tests/knowledge/wiki/ledger/test_ledger_txn.py` is placed flat as `packages/ai-parrot/tests/knowledge/wiki/test_ledger_txn.py`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_ingest.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py", "action": "MODIFY"},
    {"path": "tests/knowledge/wiki/test_ledger_store.py", "action": "MODIFY"},
    {"path": "tests/knowledge/wiki/test_ledger_index.py", "action": "MODIFY"},
    {"path": "tests/knowledge/wiki/test_ledger_integration.py", "action": "MODIFY"},
    {"path": "tests/knowledge/wiki/test_ledger_sdd_ingest.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_ledger_txn.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py#LedgerStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py#LedgerStore.ledger_transaction",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py#LedgerStore.read_cursor",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py#LedgerStore.upsert_pages_in",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py#LedgerStore.add_edges_in",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py#LedgerIndex",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py#LedgerIndex.apply_event",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py#LedgerIndex._read_issue",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py#LedgerIndex.compact",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_ingest.py#SDDGraphIngest",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore._write",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore._read"
  ]
}
```

---

## Implementation Notes

### Spec drift (follow the real code)
- The spec's `LedgerReader` lists `get_page_body`, `list_pages(category)`, `get_state`. `LedgerService.audit()`
  (`service.py:513`) also counts dangling edges with SQL, so the reader gains **`count_dangling_edges()`**
  (edges whose `dst` is not a page and does not start with `sym:` / `file:`). Line numbers moved since the
  spec: `_read()` sites are `service.py:207,338,513` (spec said 178/309/467); `from_root`/`from_dir` store
  construction is `:169`/`:193` (spec 140/164).
- Reads inside a write transaction must see that transaction's own writes (claim/close/unclaim read the
  issue after `_sync_locked` applied events in the same transaction). On SQLite this is automatic; the
  protocol docstring states it as a **contract** so TASK-4381's accumulator overlays pending writes.

### Key Constraints
- `_SQLiteLedgerTxn` wraps the `_write(operation)` connection; `ledger_transaction` still creates
  `ledger_state` first and propagates `WikiStoreBusy` unchanged.
- `ledger_read()` wraps `_read()`; a missing `ledger_state` table reads as absent state (mirror `read_cursor`).
- No `aiosqlite` import may remain in `index.py`, `sdd_ingest.py`, `service.py` (AC5:
  `grep -rn "aiosqlite" packages/ai-parrot/src/parrot/knowledge/wiki/ledger/{index,sdd_ingest,service}.py` empty).
- Keep `LedgerIndex.sync(conn=None)`'s keyword usable: rename the parameter to `txn` and grep callers
  (`grep -rn "\.sync(" packages/ai-parrot/src/parrot/knowledge/wiki/ledger`) — `_sync_best_effort` calls `sync()` bare.

---

## Implementation Blueprint

### Steps (in order)
1. Add the protocols + SQLite implementations to `ledger/store.py` — *why*: everything else types against them.
2. Rewrite `index.py`, then `sdd_ingest.py`, then `service.py` — *why*: index is the main consumer.
3. Update the four root tests; add `test_ledger_txn.py`; run all ledger tests.

### `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c -F '    async def ledger_transaction(self, operation: str) -> AsyncIterator[aiosqlite.Connection]:' …/ledger/store.py)
# BEFORE `class LedgerStore(SQLiteWikiStore):` (store.py:24) — insert the protocols and SQLite adapters
@runtime_checkable
class LedgerTxn(Protocol):
    """Backend-neutral composable ledger write (spec §3 M5).

    Reads issued through a txn MUST observe writes already issued through the same txn.
    """

    async def upsert_pages(self, pages: list[WikiPageRecord]) -> None: ...
    async def add_edges(self, edges: list[tuple]) -> None: ...
    async def get_page_body(self, concept_id: str) -> str | None: ...
    async def set_state(self, key: str, value: str) -> None: ...
    async def clear_all(self) -> None: ...
    async def list_pages(self, category: str) -> list[tuple[str, str, str]]: ...


@runtime_checkable
class LedgerReader(Protocol):
    """Read-only ledger view (replaces LedgerService's direct store._read() SQL)."""

    async def get_page_body(self, concept_id: str) -> str | None: ...
    async def list_pages(self, category: str) -> list[tuple[str, str, str]]: ...
    async def get_state(self, key: str) -> str | None: ...
    async def count_dangling_edges(self) -> int: ...


class _SQLiteLedgerReader:
    """LedgerReader over one open aiosqlite connection."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def get_page_body(self, concept_id: str) -> str | None:
        async with self._conn.execute("SELECT body FROM pages WHERE concept_id = ?", (concept_id,)) as cur:
            row = await cur.fetchone()
        return None if row is None else row[0]

    async def list_pages(self, category: str) -> list[tuple[str, str, str]]:
        async with self._conn.execute(
            "SELECT concept_id, body, updated_at FROM pages WHERE category = ?", (category,)
        ) as cur:
            return [(r[0], r[1], r[2]) for r in await cur.fetchall()]

    async def get_state(self, key: str) -> str | None:
        try:
            async with self._conn.execute("SELECT value FROM ledger_state WHERE key = ?", (key,)) as cur:
                row = await cur.fetchone()
        except aiosqlite.OperationalError:  # ledger_state not created yet
            return None
        return None if row is None else row[0]

    async def count_dangling_edges(self) -> int:
        async with self._conn.execute(
            "SELECT COUNT(*) FROM edges WHERE dst NOT IN (SELECT concept_id FROM pages)"
            " AND dst NOT LIKE 'sym:%' AND dst NOT LIKE 'file:%'"
        ) as cur:
            row = await cur.fetchone()
        return row[0] if row else 0


class _SQLiteLedgerTxn(_SQLiteLedgerReader):
    """LedgerTxn over the connection of an open `_write(operation)` transaction."""

    def __init__(self, store: "LedgerStore", conn: aiosqlite.Connection) -> None:
        super().__init__(conn)
        self._store = store

    async def upsert_pages(self, pages: list[WikiPageRecord]) -> None:
        await self._store.upsert_pages_in(self._conn, pages)

    async def add_edges(self, edges: list[tuple]) -> None:
        await self._store.add_edges_in(self._conn, edges)

    async def set_state(self, key: str, value: str) -> None:
        await self._conn.execute("INSERT OR REPLACE INTO ledger_state (key, value) VALUES (?, ?)", (key, value))

    async def clear_all(self) -> None:
        await self._conn.execute("DELETE FROM pages")
        await self._conn.execute("DELETE FROM edges")
        await self._conn.execute("DELETE FROM ledger_state")
```
```python
# REPLACE the ledger_transaction method (store.py:53-73) with:
    @asynccontextmanager
    async def ledger_transaction(self, operation: str) -> AsyncIterator[LedgerTxn]:
        """Yield a LedgerTxn inside FEAT-557's `_write(operation)`; creates `ledger_state` on first use.

        Propagates WikiStoreBusy unchanged.
        """
        async with self._write(operation) as conn:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS ledger_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            yield _SQLiteLedgerTxn(self, conn)

    @asynccontextmanager
    async def ledger_read(self) -> AsyncIterator[LedgerReader]:
        """Yield a read-only LedgerReader over `_read()`."""
        async with self._read() as conn:
            yield _SQLiteLedgerReader(conn)
```
**Why**: `upsert_pages_in`/`add_edges_in` stay as the SQLite txn's internals (spec §3 M5); `Protocol`,
`runtime_checkable` join the `typing` import. The yielded object has no `.execute` (hard cut, AC5).

### `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py` (MODIFY)
```python
# TYPE_CHECKING block (index.py:32-35): replace `import aiosqlite` with
    from parrot.knowledge.wiki.ledger.store import LedgerStore, LedgerTxn
# Retype all 14 `"aiosqlite.Connection"` occurrences → `"LedgerTxn"` and rename the parameter conn → txn
#   (sync(self, txn: "LedgerTxn | None" = None)).
# _read_issue (index.py:126-132) body becomes:
        return _decode_issue_body(await txn.get_page_body(issue_id))
# _write_issue (:157): await txn.upsert_pages([page])
# every `await self.store.add_edges_in(conn, X)` → `await txn.add_edges(X)`
# _write_cursor (:252-261) body becomes:
        await txn.set_state("cursor_offset", str(line_start))
        await txn.set_state("last_event_id", event_id)
# _rebuild_locked_with_cursor (:375-377): the three DELETEs → `await txn.clear_all()`
# compact (:549-550): `rows = await txn.list_pages("issue")`
```
**Why**: `_decode_issue_body(None)` already returns `None` (`index.py:62-74`), so a missing page keeps its meaning.

### `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_ingest.py` (MODIFY)
```python
# occurrences: 2 (`as conn:` — :99 "ledger.ingest.specs", :195 "ledger.ingest.tasks")
            async with self.store.ledger_transaction("ledger.ingest.specs") as txn:
                await txn.upsert_pages(pages)
                if edges:
                    await txn.add_edges(edges)
# same shape for "ledger.ingest.tasks"
```

### `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py` (MODIFY)
```python
# occurrences: 3 of `        async with self.store._read() as conn:` — disambiguated by the next line:
# (1) _all_issues (:207, next line SELECT concept_id, body FROM pages WHERE category = 'issue'):
        async with self.store.ledger_read() as reader:
            rows = await reader.list_pages("issue")
        result = []
        for concept_id, body, _updated_at in rows:
# (2) _issue_state (:338, next line SELECT body FROM pages WHERE concept_id = ?):
        async with self.store.ledger_read() as reader:
            body = await reader.get_page_body(issue_id)
        return _decode_issue_body(body)
# (3) audit (:513, next line SELECT COUNT(*) FROM edges …):
        async with self.store.ledger_read() as reader:
            broken_edges = await reader.count_dangling_edges()
# docstring (:8): "reads go through ``LedgerStore.ledger_read()`` (a LedgerReader)…"
```

### Tests to update (MODIFY)
```python
# tests/knowledge/wiki/test_ledger_index.py:135 — corrupt the cursor through the txn:
        async with ledger_index.store.ledger_transaction("corrupt") as txn:
            await txn.set_state("last_event_id", "not-a-real-event")
# tests/knowledge/wiki/test_ledger_index.py:172 and test_ledger_integration.py:123 — edge existence:
        edges = await store.neighbors("task:TASK-9001", rel="blocks", direction="out")
        assert any(e["concept_id"] == "task:TASK-9002" for e in edges)
# tests/knowledge/wiki/test_ledger_integration.py:84 — body via reader:
        async with service.store.ledger_read() as reader:
            state = _decode_issue_body(await reader.get_page_body(issue_id))
# tests/knowledge/wiki/test_ledger_store.py — FILL IN: rewrite the 5 conn-SQL tests (:47,:68,:97,:130,:158)
#   against txn.set_state / read_cursor, txn.upsert_pages + ledger_read().get_page_body, txn.add_edges + neighbors,
#   busy test using `await txn.get_page_body("x")` — bounded by: same assertions, no SQL on the yielded object
# tests/knowledge/wiki/test_ledger_sdd_ingest.py — FILL IN: the mock store's ledger_transaction yields a mock txn
#   (AsyncMock with upsert_pages / add_edges); assertions on store.upsert_pages_in/add_edges_in (:158,:161,:197,:200,:247,:248)
#   move to txn.upsert_pages / txn.add_edges — bounded by unchanged call-count semantics
```

### FILL IN checklist
- [ ] `test_ledger_store.py` five tests rewritten without raw SQL on the txn
- [ ] `test_ledger_sdd_ingest.py` mock fixture + assertions moved to the txn
- [ ] `LedgerIndex.sync` parameter rename — confirm no keyword caller (`grep -rn "sync(conn=" packages tests`)

---

## Acceptance Criteria

- [ ] AC5 (SQLite half): `ledger_transaction()` yields a `LedgerTxn` (`isinstance(txn, LedgerTxn)`, `not hasattr(txn, "execute")`).
- [ ] `grep -rn "aiosqlite" packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_ingest.py packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py` is empty.
- [ ] `grep -n "_read()" packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py` is empty (`test_ledger_reader_protocol`).
- [ ] Every pre-existing ledger test passes (root `tests/knowledge/wiki/test_ledger_*.py`, package `packages/ai-parrot/tests/knowledge/wiki/test_ledger_*.py`).
- [ ] `ruff check` clean on the four source files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_ledger_txn.py -q`
- `pytest tests/knowledge/wiki/test_ledger_store.py -q`
- `pytest tests/knowledge/wiki/test_ledger_index.py -q`
- `pytest tests/knowledge/wiki/test_ledger_integration.py -q`
- `pytest tests/knowledge/wiki/test_ledger_sdd_ingest.py -q`
- `pytest tests/knowledge/wiki/test_ledger_service.py -q`
- `pytest tests/knowledge/wiki/test_cli_ledger.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_ledger_list_issues.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/test_ledger_txn.py
import ast
from pathlib import Path

from parrot.knowledge.wiki.ledger.store import LedgerReader, LedgerStore, LedgerTxn
from parrot.knowledge.wiki.store import WikiPageRecord

LEDGER_SRC = Path(__file__).parents[3] / "src" / "parrot" / "knowledge" / "wiki" / "ledger"


async def test_ledger_transaction_yields_txn_not_connection(tmp_path):
    store = LedgerStore(tmp_path / "ledger.db", wiki_name="ledger")
    async with store.ledger_transaction("t") as txn:
        assert isinstance(txn, LedgerTxn)
        assert not hasattr(txn, "execute")


async def test_txn_reads_own_writes_and_state(tmp_path): ...   # upsert_pages then get_page_body in same txn; set_state → read_cursor
async def test_clear_all_and_list_pages(tmp_path): ...          # list_pages("issue") tuples; clear_all empties pages/edges/state
async def test_ledger_read_is_reader(tmp_path): ...             # isinstance(reader, LedgerReader); get_state before first txn → None
async def test_count_dangling_edges_excludes_sym_and_file(tmp_path): ...


def test_no_aiosqlite_in_ledger_consumers():
    for name in ("index.py", "sdd_ingest.py", "service.py"):
        assert "aiosqlite" not in (LEDGER_SRC / name).read_text(encoding="utf-8")
    assert "._read()" not in (LEDGER_SRC / "service.py").read_text(encoding="utf-8")
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug helixdb-provider --feature-id FEAT-670`)
2. **Read the spec** (§3 M5, §7 "Ledger hard cut" risk)
3. **Check dependencies** — none
4. **Verify the Codebase Contract** — re-run the `grep -c -F` anchors above (FEAT-633 may move lines)
5. **Update status** → `"in-progress"`, commit only the index
6. **Implement**; behaviour on SQLite must be byte-identical (same SQL, same `_write` operation names)
7. **Verify** with `PYTHONPATH=packages/ai-parrot/src`; root tests too
8. **Commit the code** — only the listed files
9. **Close** with `scripts/sdd/close_task.sh TASK-4380 helixdb-provider verified`
10. **Fill in the Completion Note**, commit the SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
