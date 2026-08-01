# TASK-2072: ARCHIVE page category + default ranking exclusion

**Feature**: FEAT-402 — Supervised Wiki Ingestion (charter-driven triage + HITL manifest review)
**Spec**: `sdd/specs/supervised-wiki-ingestion.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 4** of the spec (§3). Spec Q&A resolved that
archive-routed documents become wiki pages with a new `archive` category
that is **excluded from default query ranking** but retrievable via an
explicit category filter. This task adds the enum value, the search-plane
exclusion, and `WikiConfig.charter_path`. It touches the read path, so the
regression test is the point.

---

## Scope

- Add `ARCHIVE = "archive"` to `WikiPageCategory`
  (`packages/ai-parrot/src/parrot/knowledge/wiki/models.py`).
- Add `charter_path: Optional[Path] = None` field to `WikiConfig` (with
  Field description; no validator needed).
- Exclude the `archive` category from default ranking:
  - `SQLiteWikiStore.search_fts` — when `category` is None (default),
    filter out archive-category rows; an explicit `category="archive"`
    still returns them.
  - `WikiCombinedSearch.search` — ensure combined mode (fts + vector
    merge) also excludes archive by default; add an explicit opt-in path
    (e.g. `include_archived: bool = False` param — keep the surface minimal
    and backward-compatible).
- Write tests: category value, default exclusion, explicit-filter retrieval.

**NOT in scope**: creating archive pages (TASK-2074 routes them), charter
loading (TASK-2069), any CLI change (TASK-2075).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/models.py` | MODIFY | `WikiPageCategory.ARCHIVE`; `WikiConfig.charter_path` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` | MODIFY | default archive exclusion in `search_fts` (SQLite impl) |
| `packages/ai-parrot/src/parrot/knowledge/wiki/search.py` | MODIFY | combined-search default exclusion + opt-in |
| `tests/knowledge/wiki/test_models.py` | MODIFY | category value test |
| `tests/knowledge/wiki/test_search.py` | MODIFY | exclusion + explicit-filter tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `ad6365242` (2026-08-02).

### Verified Imports
```python
from parrot.knowledge.wiki.models import WikiConfig, WikiPageCategory
from parrot.knowledge.wiki.store import BaseWikiStore, SQLiteWikiStore
from parrot.knowledge.wiki.search import WikiCombinedSearch
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/models.py
class WikiPageCategory(str, Enum):        # line 25; values at 38-44
    # 7 values today: SUMMARY, ENTITY, CONCEPT, COMPARISON, OVERVIEW, SYNTHESIS, ANSWER
class WikiConfig(BaseModel):              # line 47
    page_categories: list[WikiPageCategory]   # line 80
    search_weights: dict[str, float]          # line 84 (validator 114-140)

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
class BaseWikiStore:                      # line 279
    async def search_fts(self, query: str, category: Optional[str] = None,
                         limit: int = 10) -> list[dict[str, Any]]: ...  # abstract 334
    async def search_vector(self, embedding: list[float],
                            limit: int = 10) -> list[dict[str, Any]]: ...  # abstract 339
class SQLiteWikiStore(BaseWikiStore):     # line 431
    # search_fts impl 987-992 (FTS5 BM25 over title/summary/body)
    # search_vector impl 1025-1029 (brute-force cosine)

# packages/ai-parrot/src/parrot/knowledge/wiki/search.py
class WikiCombinedSearch:                 # line 32; __init__ 47
    async def search(self, query: str, mode: str = "combined", top_k: int = 10,
                     tree_name: Optional[str] = None,
                     weights: Optional[dict[str, float]] = None) -> list[WikiSearchResult]: ...  # 85-92
    async def find_related(...): ...      # 235
```

### Does NOT Exist
- ~~`WikiPageCategory.ARCHIVE`~~ — you are adding it (7 values today).
- ~~an existing category-exclusion mechanism in search~~ — `search_fts` only has positive `category` filtering; the default-exclusion logic is new.
- Note: the ArangoDB store backend also implements the abstract search
  surface — check `tests/knowledge/wiki/test_arango_store.py` expectations;
  if the Arango impl filters by category, mirror the exclusion there or
  document why not (keep scope minimal, but do not silently break parity).

---

## Implementation Notes

### Key Constraints
- **Backward compatibility is the hard constraint**: existing search
  behavior for non-archive pages must be unchanged (no result-order
  changes, no signature breaks — new params must default to prior behavior).
- Enum is `str, Enum` — new value is `"archive"` lowercase, matching
  existing value style (models.py:38-44).
- Keep the SQL change narrow: a `WHERE category != 'archive'` (or
  equivalent) only when no explicit category filter is passed.

### References in Codebase
- `tests/knowledge/wiki/test_search.py`, `test_store.py`, `test_models.py` — existing suites this must not regress.

---

## Acceptance Criteria

- [ ] `WikiPageCategory.ARCHIVE == "archive"`; `WikiConfig.charter_path` defaults to None.
- [ ] Archive-category pages absent from default `search_fts` / combined `search` results.
- [ ] Explicit `category="archive"` (or opt-in param) returns archived pages.
- [ ] Existing search/store/model tests still pass unchanged: `pytest tests/knowledge/wiki/test_search.py tests/knowledge/wiki/test_store.py tests/knowledge/wiki/test_models.py -v`
- [ ] `ruff check` clean on the three modified modules.

---

## Test Specification

```python
# tests/knowledge/wiki/test_models.py (add)
def test_archive_category_value():
    assert WikiPageCategory.ARCHIVE == "archive"

# tests/knowledge/wiki/test_search.py (add)
async def test_search_excludes_archive_by_default(...): ...
async def test_search_explicit_archive_filter_returns_archived(...): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none (parallel-safe; shares no files with TASK-2069)
3. **Verify the Codebase Contract** — confirm signatures/lines above still hold
4. **Update status** in `sdd/tasks/index/supervised-wiki-ingestion.json` → `"in-progress"`
5. **Implement**, **verify** acceptance criteria
6. **Move this file** to `sdd/tasks/completed/` and **update index** → `"done"`
7. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
