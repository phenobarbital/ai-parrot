# TASK-2361: Explicit read-only open for `SQLiteWikiStore` (`read_only=True`)

**Feature**: FEAT-450 — Namespaces for `wikitoolkit` (multi-wiki federation)
**Spec**: `sdd/specs/wiki-namespaces.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (store half), G5. `SQLiteWikiStore._connect` (store.py:514-578) opens
**write-first**: it may `mkdir` (488), replay the schema and call `self._migrate(conn)` (565); the
read-only ladder `_connect_readonly` (580-655) engages only when the write attempt fails with a
read-only-environment error (573-576). A federated read of a *sibling repo's* `wiki.db` must never
migrate or mutate it, so the store needs an explicit opt-in read-only mode that goes straight to
the ladder.

---

## Scope

- Add keyword-only `read_only: bool = False` to `SQLiteWikiStore.__init__`. When `True`:
  no `mkdir` of the parent; if `db_path` does not exist raise `FileNotFoundError` at construction
  (so the resolver classifies the namespace as `unbuilt`); `_connect()` yields from
  `_connect_readonly()` directly (no schema replay, no `_migrate`, no read-only-error detection
  round-trip).
- Every write method (`upsert_pages`, `add_edges`, `replace_source_slice`, `delete_page`,
  `upsert_embedding`, `rebuild_from_tree`) raises `PermissionError("read-only wiki store: <path>")`
  before touching the connection when `read_only` is set.
- Expose `read_only` as a read-only property.
- Tests in `tests/knowledge/wiki/test_store.py` (extend): no migration on a stale-schema plane, no
  `-wal`/`-shm` left behind on a quiescent plane, writes refused, missing db raises.

**NOT in scope**: `create_wiki_store` changes (the resolver in TASK-2362 constructs
`SQLiteWikiStore(db_path, read_only=True)` directly — see spec §7 gotcha on `_open_store` mkdir);
InMemory/Arango stores.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` | MODIFY | `read_only` mode |
| `tests/knowledge/wiki/test_store.py` | MODIFY | add tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.store import BaseWikiStore, SQLiteWikiStore, WikiPageRecord, create_wiki_store   # store.py:289,441,215,1217
import aiosqlite  # already imported by store.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
class SQLiteWikiStore(BaseWikiStore):                                       # 441
    @classmethod
    def _is_readonly_env_error(cls, exc: sqlite3.OperationalError) -> bool  # 474
    def __init__(self, db_path: str | Path, wiki_name: str = "") -> None    # 485
        self._db_path = Path(db_path)                                       # 486
        self._db_path.parent.mkdir(parents=True, exist_ok=True)  # 488 — tolerant on EROFS/EACCES/EPERM only when file exists (493-498)
        self._wiki_name = wiki_name; self._warned_read_only = False         # 499-500
    @property
    def db_path(self) -> Path                                               # 505
    async def _connect(self) -> AsyncIterator[aiosqlite.Connection]         # 514 (asynccontextmanager) — schema probe/replay, await self._migrate(conn) at 565, fallback at 573-576
    async def _connect_readonly(self) -> AsyncIterator[aiosqlite.Connection]   # 580 — mode=ro then immutable=1, probe query; refuses immutable when a live -wal exists
    def _log_read_only_once(self) -> None                                   # 656
    async def _migrate(self, conn) -> None                                  # 666
    async def upsert_pages(self, pages) -> int                              # 754
    async def add_edges(self, edges) -> int                                 # 770
    async def replace_source_slice(self, source_id, pages, edges=None) -> dict   # 788
    async def delete_page(self, concept_id) -> bool                         # 874
    async def upsert_embedding(self, concept_id, vector, model="") -> None  # 901
    async def get_page / list_pages / search_fts / search_vector / neighbors / dump_* / stats / lint   # 926-1209 (all use `async with self._connect()`)
class BaseWikiStore(ABC):
    async def rebuild_from_tree(self, tree, content_loader=None, source_id=None) -> dict   # 382 (concrete; writes via upsert_pages)
def create_wiki_store(storage_dir, wiki_name="", backend="sqlite", **kwargs) -> BaseWikiStore   # 1217 — sqlite → SQLiteWikiStore(storage_dir / "wiki.db", wiki_name=wiki_name)
```

### Does NOT Exist
- ~~`SQLiteWikiStore(read_only=...)`~~ — no such kwarg today; ~~`SQLiteWikiStore.read_only`~~ property — you add both.
- ~~`create_wiki_store(..., read_only=True)`~~ — not added in this task (resolver constructs directly).
- ~~`_connect(readonly=True)`~~ — `_connect` takes no arguments.
- `_warned_read_only` / `_log_read_only_once` (500, 656) are the *fallback* path's warning; do not reuse them to mean "opt-in".

---

## Implementation Notes

### Pattern to Follow
```python
# store.py:514-578 — keep the existing write-first path intact for read_only=False.
@asynccontextmanager
async def _connect(self):
    if self._read_only:
        async with self._connect_readonly() as conn:
            yield conn
        return
    ...existing body unchanged...
```
Guard writes with one helper: `def _assert_writable(self) -> None: if self._read_only: raise PermissionError(...)`.

### Key Constraints
- `read_only` must be keyword-only to keep `create_wiki_store`'s positional call (1237) valid.
- The "no sidecars" test: open a freshly built plane that has been checkpointed (no `-wal`),
  run `search_fts`, assert no `wiki.db-wal` / `wiki.db-shm` was created and `meta` is unchanged.
- The "no migration" test: craft a db with the base schema but missing a column added by
  `_migrate` (see `store.py:117-135` comments on post-FEAT-260 columns), open read-only, query,
  assert `PRAGMA table_info(pages)` unchanged.

### References in Codebase
- `store.py:580-655` `_connect_readonly` docstring — semantics to preserve.
- `tests/knowledge/wiki/test_store.py` — existing store fixtures.

---

## Acceptance Criteria

- [ ] `SQLiteWikiStore(p, read_only=True)` on a missing file raises `FileNotFoundError`
- [ ] Read methods work in read-only mode; write methods raise `PermissionError`
- [ ] No `_migrate`, no `mkdir`, no sidecar creation on a quiescent plane (tests prove it)
- [ ] `read_only=False` behaviour byte-for-byte unchanged; existing `tests/knowledge/wiki/test_store.py` still green
- [ ] `pytest tests/knowledge/wiki/test_store.py -v`; `ruff check .../store.py`

---

## Test Specification

```python
# tests/knowledge/wiki/test_store.py (append)
import pytest
from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiPageRecord

async def _build(tmp_path):
    s = SQLiteWikiStore(tmp_path / "wiki.db")
    await s.upsert_pages([WikiPageRecord(concept_id="file:a.md", title="A", body="alpha beta")])
    return tmp_path / "wiki.db"

async def test_read_only_reads_and_refuses_writes(tmp_path):
    db = await _build(tmp_path)
    ro = SQLiteWikiStore(db, read_only=True)
    assert ro.read_only
    assert await ro.get_page("file:a.md")
    assert await ro.search_fts("alpha")
    with pytest.raises(PermissionError):
        await ro.upsert_pages([WikiPageRecord(concept_id="file:b.md", title="B")])
    with pytest.raises(PermissionError):
        await ro.delete_page("file:a.md")

def test_read_only_missing_db_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        SQLiteWikiStore(tmp_path / "nope" / "wiki.db", read_only=True)
    assert not (tmp_path / "nope").exists()   # no mkdir

async def test_read_only_creates_no_sidecars_or_migration(tmp_path):
    db = await _build(tmp_path)
    # checkpoint so the plane is quiescent, then snapshot schema
    ...PRAGMA wal_checkpoint(TRUNCATE) via sqlite3...
    before = (db.read_bytes(), sorted(p.name for p in tmp_path.iterdir()))
    ro = SQLiteWikiStore(db, read_only=True)
    await ro.search_fts("alpha")
    assert sorted(p.name for p in tmp_path.iterdir()) == before[1]
    assert db.read_bytes() == before[0]
```

---

## Agent Instructions

1. Read spec §2 New Public Interfaces (`SQLiteWikiStore`), §3 Module 2, §6, §7 gotchas (mkdir).
2. Verify the contract; implement; run the store tests.
3. Update index → `done`; move to `sdd/tasks/completed/`; fill the Completion Note.

---

## Completion Note

**Completed by**: Claude Code (main session)
**Date**: 2026-08-23
**Notes**: SQLiteWikiStore(read_only=True): no mkdir, FileNotFoundError on an unbuilt plane, _connect() bypasses the write-first probe/replay/_migrate, all six write methods raise PermissionError via _assert_writable (no-op hook on BaseWikiStore so rebuild_from_tree is covered too), read_only property. 8 new tests.

**Deviations from spec**: Added _sidecars_quiescent() + _connect_immutable(): in explicit read-only mode a quiescent plane is opened immutable=1 FIRST, because the ladder's mode=ro rung creates -shm/-wal sidecars when the directory is writable, which the AC forbids. A live sidecar still takes the existing mode=ro ladder. _log_read_only_once() is silenced for an intentional read-only open.
