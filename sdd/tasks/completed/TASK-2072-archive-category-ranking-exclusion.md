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

**Completed by**: sdd-worker (Claude, autonomous)
**Date**: 2026-08-02
**Notes**: Added `WikiPageCategory.ARCHIVE = "archive"` (8th value) and
`WikiConfig.charter_path: Optional[Path] = None` to models.py.
`SQLiteWikiStore.search_fts` now excludes `category="archive"` rows when
`category` is not explicitly given (`AND (p.category IS NULL OR
p.category != 'archive')`, using the plain-string convention already
established in store.py's "no enum ceremony in the machine plane"
design), while an explicit `category="archive"` still returns them
unchanged. `WikiCombinedSearch.search`/`_search_store` gained an
`include_archived: bool = False` parameter: the lexical leg issues a
supplemental `category="archive"` query and merges it in when
`include_archived=True` (since `search_fts`'s single filter can express
"default" or "exactly this category" but not "no filter at all"); the
vector leg (which has no category filter at the store layer at all) is
post-filtered by `WikiSearchResult.category` in `WikiCombinedSearch`
itself, skipped when `include_archived=True`. Updated
`test_all_categories_exist`/`test_expected_values`/`test_defaults` in
test_models.py to account for the new 8th enum value (these were the
only *existing* tests that needed updating; all other pre-existing
search/store/model tests pass unchanged). Added
`test_archive_category_value`, `test_charter_path_defaults_none`,
`test_charter_path_accepts_explicit_path` (test_models.py) and a new
`TestArchiveExclusion` class in test_search.py (4 tests: lexical-leg
default exclusion, explicit opt-in inclusion, vector-leg default
exclusion, vector-leg opt-in) using a `StubWikiStore` that mirrors the
real `search_fts` archive-exclusion contract without depending on SQLite.
All 114 tests across test_search.py/test_store.py/test_models.py pass
(`pytest tests/knowledge/wiki/test_search.py tests/knowledge/wiki/
test_store.py tests/knowledge/wiki/test_models.py -v`); also re-ran
test_arango_store.py/test_file_store.py (54 tests) to confirm no
cross-backend regression.

**ArangoDB parity note** (per the task's Codebase Contract "Does NOT
Exist" section): `arango_store.py:524-561`'s `search_fts` was checked —
it has the SAME pre-FEAT-402 gap (no default archive exclusion; a plain
`FILTER doc.category == @category` only applied when `category` is
explicitly given). `arango_store.py` is **not** in this task's Files to
Create/Modify list, so it was intentionally left unmodified per file
fidelity — flagging this as a follow-up gap for whichever task/feature
next touches the ArangoDB backend, rather than expanding this task's
scope.

**Deviations from spec**: none in class/field names or exclusion
behavior. One judgment call on the "ruff check clean" acceptance
criterion: `models.py`/`store.py`/`search.py` carry substantial
pre-existing `ruff` findings (mostly `UP045` "use `X | None`" on
`Optional[...]` annotations already used pervasively throughout these
files, plus unrelated `SIM117` nested-`with` hits elsewhere in
store.py). Verified via `git diff` isolation that none of these
pre-existing findings sit on lines this task added or modified, and the
one new `Optional[Path]` field (`charter_path`) matches the file's own
established convention (5 other `Optional[...]` fields already present).
Per the "no scope creep" rule, pre-existing lint debt across these hot,
shared files was left untouched rather than auto-fixed wholesale.
