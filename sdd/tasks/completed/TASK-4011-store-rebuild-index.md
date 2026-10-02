# TASK-4011: BaseWikiStore.rebuild_index + index_drift (SQLite FTS rebuild)

**Feature**: FEAT-625 — wikitoolkit lint
**Spec**: `sdd/specs/wikitoolkit-lint.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4. There is no public FTS rebuild; the `fts-index-drift` fix (TASK-4014) needs one.

---

## Scope

- Add concrete defaults `rebuild_index()` → `{"rebuilt": []}` and `index_drift()` → `{}` to `BaseWikiStore` (NOT abstract — Arango/Postgres/InMemory/Federated inherit them).
- Override both in `SQLiteWikiStore`: drift = row-count mismatch `pages` vs `pages_fts`, `symbols` vs `symbols_fts`; rebuild = FTS5 `'rebuild'` for each table, then re-set `schema_version` meta.
- Write tests on a temp SQLite plane.

**NOT in scope**: Lint rules; any other backend override.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` | MODIFY | Add rebuild_index/index_drift |
| `packages/ai-parrot/tests/knowledge/wiki/test_store_rebuild_index.py` | CREATE | Tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ 350d206f0 (2026-10-03). Re-verify before coding.

### Verified Imports
```python
from parrot.knowledge.wiki.store import BaseWikiStore, SQLiteWikiStore, SCHEMA_VERSION, create_wiki_store  # verified: wiki/store.py:525, :50; WikiStore alias + create_wiki_store after :2369
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
class BaseWikiStore(ABC):                                              # :525
    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int: ...  # :544
    async def add_edges(self, edges: list[tuple]) -> int: ...          # :547  (src, dst, rel, provenance)
    async def get_page(self, concept_id: str, include_body: bool = True) -> Optional[dict[str, Any]]: ...  # :565
    async def list_pages(self, category=None, limit: int = 100, origin: Optional[list[str]] = None) -> list[dict[str, Any]]: ...  # :568
    async def dump_pages(self) -> list[dict[str, Any]]: ...            # :590  keys: concept_id,node_id,title,category,summary,body,source_id,token_count,created_at,updated_at,content_hash
    async def dump_edges(self) -> list[dict[str, Any]]: ...            # :593  keys: src,dst,rel
    async def orphan_sources(self) -> list[str]: ...                   # :600
    async def broken_edges(self) -> list[dict[str, Any]]: ...          # :603  keys: src,dst,rel
    async def missing_bodies(self) -> list[str]: ...                   # :606
# wiki/store.py:1467 (inside _migrate_fts :1418) — the rebuild statement pattern:
#     await conn.execute(f"INSERT INTO {table}({table}) VALUES('rebuild')")
# SQLiteWikiStore uses `async with self._read() as conn` for reads (e.g. :2214); FILL IN: locate the write-connection context manager (grep '_write' in store.py) before use
```

### Does NOT Exist
- ~~a public FTS rebuild on the store~~ — only inside `SQLiteWikiStore._migrate_fts` (`wiki/store.py:1418`); TASK-4011 adds `rebuild_index`
- ~~`BaseWikiStore.rebuild_index`~~ / ~~`index_drift`~~ — added by this task

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/store.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_store_rebuild_index.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Async throughout; never block the event loop (file I/O via `asyncio.to_thread`).
- Pydantic v2; `self.logger` / `logging.getLogger(__name__)`; Google docstrings; 120 cols.
- Writes only through store/export APIs — never raw SQL from a rule; never delete pages or edges (spec AC2).

### References in Codebase
- Spec `sdd/specs/wikitoolkit-lint.spec.md` §2–§7 (rule ids, severities, decisions are fixed there).

---

## Implementation Blueprint

### Steps (in order)
1. Insert the base defaults right after the abstract `broken_edges` — *why*: keeps integrity helpers together; defaults avoid touching other backends.
2. Add SQLite overrides next to `missing_bodies` (:2364) — *why*: same section as the other integrity queries.

### `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    async def broken_edges(self) -> list[dict[str, Any]]: ...' wiki/store.py)
# AFTER — insert below `    async def broken_edges(self) -> list[dict[str, Any]]: ...` (verified: wiki/store.py:603)
    async def rebuild_index(self) -> dict[str, Any]:
        """Rebuild derived search indexes and repair ``meta``.

        Default is a no-op for backends without derived indexes.

        Returns:
            ``{"rebuilt": [<index names>]}``.
        """
        return {"rebuilt": []}

    async def index_drift(self) -> dict[str, int]:
        """Return ``{index_name: row_count_delta}`` for drifted indexes; ``{}`` when clean."""
        return {}

# --- SQLiteWikiStore overrides: insert AFTER the SQLite `missing_bodies` method (verified: wiki/store.py:2364-2367)
    async def rebuild_index(self) -> dict[str, Any]:
        """Run FTS5 'rebuild' on pages_fts and symbols_fts and re-stamp schema_version."""
        # FILL IN: open a write connection; for table in ("pages_fts", "symbols_fts"):
        #          await conn.execute(f"INSERT INTO {table}({table}) VALUES('rebuild')"); commit;
        #          then set meta schema_version = SCHEMA_VERSION; return {"rebuilt": [...]}
        raise NotImplementedError

    async def index_drift(self) -> dict[str, int]:
        """Compare COUNT(*) of content vs FTS tables."""
        # FILL IN: SELECT COUNT(*) for pages/pages_fts and symbols/symbols_fts; include only non-zero deltas
        raise NotImplementedError
```

**Why this shape**: Spec M4 fixes the signatures. Defaults are concrete so no other backend changes (AC7). External-content FTS5 'rebuild' is the same statement `_migrate_fts` already trusts.

### FILL IN checklist
- [ ] SQLite write-connection helper name
- [ ] `index_drift` count queries

---

## Acceptance Criteria

- [ ] Base defaults return `{"rebuilt": []}` / `{}`
- [ ] SQLite drift detected after manual FTS row deletion and cleared by `rebuild_index()`
- [ ] Existing wiki store tests still pass
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/wiki/test_store_rebuild_index.py -v`
- [ ] No lint errors: `ruff check` on the touched files

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_store_rebuild_index.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/test_store_rebuild_index.py
async def test_fts_rebuild_fix(tmp_path):
    # FILL IN: build a SQLiteWikiStore in tmp_path, upsert 2 pages, DELETE FROM pages_fts directly,
    #          assert (await store.index_drift()) != {}, await store.rebuild_index(), assert drift == {}
    ...
```

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug wikitoolkit-lint --feature-id FEAT-625`), never on `dev`.
2. Check every Depends-on task is `done` in `sdd/tasks/index/wikitoolkit-lint.json`.
3. Verify the Codebase Contract; fix it first if stale.
4. Implement from the blueprint; complete every `# FILL IN:`; never change fixed signatures/paths.
5. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
6. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4011 wikitoolkit-lint verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none

## Completion Note

Implemented by sonnet (native), 1 attempt; index_drift counts the *_fts_docsize shadow tables (FTS5 external-content COUNT(*) reads the content table and can never drift). Merged via coder_merge. Merge-tier run: 1520 passed, 2 failed — both in tests/sdd/test_ledger_lifecycle_acceptance.py, unrelated to this task (pass on main checkout, fail in worktree; filed issue:dc663a223799). Closed via close_task.sh, not finalize_task (no green validation ref).
