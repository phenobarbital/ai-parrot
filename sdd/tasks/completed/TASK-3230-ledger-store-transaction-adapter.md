# TASK-3230: LedgerStore transaction adapter and cursor state

**Feature**: FEAT-566 — SDD Work Ledger
**Spec**: `sdd/specs/sdd-work-ledger.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3226, TASK-3228
**Assigned-to**: unassigned

---

## Context

Store-adapter half of spec §3 Module 5. Ledger operations need one composable writer transaction, while FEAT-557 remains the exclusive owner of SQLite policy, begin/commit/rollback, timeout, migration, and busy translation.

## Scope

- Create `LedgerStore(SQLiteWikiStore)` with `ledger_transaction`, cursor reads, and connection-scoped page/edge helpers.
- Create/read `ledger_state` only inside FEAT-557 `_write`; fresh reads return `(0, None)` without DDL.
- Forward FEAT-557 `sqlite_policy`/`persistent_writer` unchanged and propagate `WikiStoreBusy` unchanged.
- Test read purity, state creation, and helper delegation.

**NOT in scope**: modifying `store.py`, `sources.py`, FEAT-557 project fields, or event reduction/claim semantics.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py` | CREATE | Ledger SQLite specialization. |
| `tests/knowledge/wiki/test_ledger_store.py` | CREATE | Cursor/transaction contract tests. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiPageRecord
# Only after TASK-3226 / FEAT-557 merge:
from parrot.knowledge.wiki.store import SQLitePragmaPolicy, WikiStoreBusy
```

### Existing Signatures to Use
```python
# store.py:774, 1223, 1267; FEAT-557 contract in spec Module 2.1
class SQLiteWikiStore(BaseWikiStore):
    async def _upsert_pages_conn(self, conn, pages: list[WikiPageRecord]) -> None: ...
    async def _insert_edges_conn(self, conn, edges: list[tuple]) -> None: ...
    async def _read(self): ...
    async def _write(self, operation: str): ...
```

### Does NOT Exist
- ~~`LedgerStore` / `ledger_state`~~ — this task creates them.
- ~~ledger-owned `BEGIN`, `COMMIT`, `ROLLBACK`, `PRAGMA`, or busy timeout code~~ — prohibited.

## Acceptance Criteria

- [ ] Writes run through FEAT-557 `_write(operation)` and raw busy errors are not caught.
- [ ] Reads issue no schema-creating statements when `ledger_state` is absent.
- [ ] Cursor state is transactionally initialized and readable after commit.
- [ ] `pytest tests/knowledge/wiki/test_ledger_store.py -q` passes after FEAT-557 merges.

## Test Specification

Use FEAT-557's read-path SQL-trace approach; do not duplicate its generic SQLite contention suite.

