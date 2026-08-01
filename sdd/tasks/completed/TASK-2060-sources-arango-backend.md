# TASK-2060: SourceCollectionManager ArangoDB Backend

**Feature**: FEAT-400 — WikiToolkit ArangoDB Backend
**Spec**: `sdd/specs/wikitoolkit-arangodb-backend.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2057
**Assigned-to**: unassigned

---

## Context

Adds `"arangodb"` as a third backend to `SourceCollectionManager`, storing
source metadata in a `wiki_sources` ArangoDB collection instead of SQLite
or JSON. Corresponds to Module 4 in the spec.

---

## Scope

- Add `"arangodb"` to the accepted `backend` values in `SourceCollectionManager`.
- Implement ArangoDB-backed `_upsert()`, `list_sources()`, `get_source()`,
  `remove_source()`, and `_find_id_by_uri()` using the shared `AsyncDB`
  connection from `ArangoDBWikiStore`.
- Handle the async/sync boundary: the public API is synchronous but ArangoDB
  operations are async. Use `asyncio` bridging.
- Write unit tests.

**NOT in scope**:
- ArangoDBWikiStore implementation (TASK-2057)
- Config changes (TASK-2058)
- CLI changes (TASK-2061)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/sources.py` | MODIFY | Add `"arangodb"` backend |
| `tests/knowledge/wiki/test_sources_arango.py` | CREATE | Unit tests for arangodb backend |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.wiki.sources import SourceCollectionManager  # verified: sources.py:64
from parrot.knowledge.wiki.models import SourceManifestEntry       # verified: models.py
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/sources.py
class SourceCollectionManager:
    def __init__(self, sources_dir: Path, db_path: Optional[Path] = None,
        backend: Literal["sqlite", "json"] = "sqlite") -> None: ...     # line 64
    def add_source(self, path: Path) -> SourceManifestEntry: ...        # line 111
    def list_sources(self) -> list[SourceManifestEntry]: ...             # line 153
    def get_source(self, source_id: str) -> Optional[SourceManifestEntry]: ...  # line 168
    def is_stale(self, source_id: str) -> bool: ...                     # line 186
    def mark_ingested(self, source_id: str, pages_generated: list[str],
        status: str = "ingested") -> Optional[SourceManifestEntry]: ...  # line 229
    def remove_source(self, source_id: str) -> bool: ...                # line 268
    def find_by_uri(self, source_uri: str) -> Optional[str]: ...        # line 294
    # Backend validation at line 84: if backend not in ("sqlite", "json"): raise ValueError
```

### Does NOT Exist

- ~~`SourceCollectionManager(backend="arangodb")`~~ — not accepted yet; this task adds it
- ~~`SourceCollectionManager._async_upsert()`~~ — no async methods exist yet

---

## Implementation Notes

### Async/Sync Bridging Strategy

The public methods are sync. For the ArangoDB backend, implement private async
methods and call them via `asyncio`:

```python
def _arangodb_upsert(self, entry: SourceManifestEntry) -> None:
    loop = asyncio.get_event_loop()
    if loop.is_running():
        # Already in async context — schedule as task
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            pool.submit(asyncio.run, self._async_upsert(entry)).result()
    else:
        asyncio.run(self._async_upsert(entry))
```

Alternatively, accept an `asyncdb.AsyncDB` connection in `__init__` when
`backend="arangodb"` and let the caller manage the event loop.

### Collection Schema

The `wiki_sources` collection stores documents matching `SourceManifestEntry`:
```python
{
    "_key": source_id,
    "source_id": str,
    "source_uri": str,
    "file_hash": str,
    "mtime": float,
    "ingested_at": str,
    "pages_generated": list[str],
    "status": str,
}
```

### Key Constraints

- Extend `backend` validation at line 84 to include `"arangodb"`
- The `__init__` signature needs a new optional param for the ArangoDB
  connection (e.g., `arango_db: Optional[AsyncDB] = None`)
- Must NOT break existing sqlite or json backends

---

## Acceptance Criteria

- [ ] `SourceCollectionManager(backend="arangodb", arango_db=...)` accepted
- [ ] `add_source()`, `list_sources()`, `get_source()` work with ArangoDB
- [ ] `is_stale()` and `mark_ingested()` work correctly
- [ ] `remove_source()` deletes from ArangoDB collection
- [ ] Existing sqlite and json backends unaffected
- [ ] Tests pass: `pytest tests/knowledge/wiki/test_sources_arango.py -v`

---

## Completion Note

Added `"arangodb"` to `SourceCollectionManager`'s accepted `backend`
values (`Literal["sqlite", "json", "arangodb"]`) plus a new `arango_db:
Optional[Any]` constructor param — a connected `asyncdb` ArangoDB driver
instance (the same connection `ArangoDBWikiStore` uses internally),
required when `backend="arangodb"` (raises `ValueError` otherwise, same
as the pre-existing unknown-backend validation).

Implemented the async ArangoDB-backed helpers (`_async_upsert`,
`_async_list_sources`, `_async_get_source`, `_async_remove_source`,
`_async_find_id_by_uri`) against a `wiki_sources` collection (literal
`_ARANGO_SOURCES_COLLECTION = "wiki_sources"`, duplicated rather than
imported from `arango_store.py` so sqlite/json-only consumers never pull
in `asyncdb`), using the same AQL UPSERT / `NoDataFound`-as-empty-result
handling pattern as `ArangoDBWikiStore._query`/`_execute`. Public sync
methods (`_upsert`, `list_sources`, `get_source`, `remove_source`,
`_find_id_by_uri`) dispatch to these via a new `_run_async()` bridge:
`asyncio.run()` when no loop is running, otherwise offloaded to a
`ThreadPoolExecutor` (nested `asyncio.run()` cannot run inside an active
loop) — matching the task's suggested bridging strategy. `add_source()`,
`is_stale()`, `mark_ingested()`, and `find_by_uri()` needed no changes —
they already call through the dispatch points above.

18 unit tests added in `tests/knowledge/wiki/test_sources_arango.py`
(construction/validation, all 5 CRUD dispatch paths, `mark_ingested`
round-trip, and the AQL bridging helpers' error handling), all passing.
Full `tests/knowledge/wiki/` suite (658 tests) re-run — no regressions on
the sqlite/json backends. `ruff check` on `sources.py` shows 9 `UP045`
findings (up from a 5-finding baseline) — all on the new `Optional[Any]`/
`Optional[SourceManifestEntry]` annotations this task added, following
the exact same `Optional[...]` convention used throughout the rest of
this file and every sibling module in `parrot/knowledge/wiki/` (none of
which have ever had this rule auto-fixed) — not new lint debt by any
different standard than the rest of the codebase.
