# TASK-1935: `ParrotWikiOrigin` adapter (WikiStore direct: FTS + optional vector leg)

**Feature**: FEAT-379 — MultiStoreSearch Toolkit with PageIndex, GraphIndex & ParrotWiki Origins
**Spec**: `sdd/specs/multistoresearchtool-parrotwiki.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1932
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 6: the ParrotWiki (LLM-Wiki) origin adapter.
Resolved decision: the adapter calls **`WikiStore` directly**
(`search_fts` / `search_vector`) — it does NOT delegate to
`WikiCombinedSearch` (PageIndex/GraphIndex have their own adapters; wiki-plane
results stay purely "wiki" origin).

---

## Scope

- Implement `ParrotWikiOrigin(SearchOrigin)` in
  `parrot_tools/multistoresearch/origins/wiki.py`.
- Constructor: `store` (`BaseWikiStore` instance), optional `embedder`
  (async `text -> list[float]` callable), optional `category` filter,
  `name: str = "wiki"`, `description` (default explains the LLM-wiki plane),
  optional `timeout`.
- `search`: when an `embedder` is configured, embed the query and call
  `store.search_vector(embedding, limit=k)`; otherwise fall back to
  `store.search_fts(query, category=..., limit=k)` (lexical leg). Normalize
  row dicts → `OriginHit` (read `SQLiteWikiStore.search_fts` return shape in
  the source before implementing).
- `supports_fts = True`; `fts_search` always calls
  `store.search_fts(query, category=..., limit=k)`.
- Unit tests with a fake store (protocol of `BaseWikiStore`) and, if cheap,
  an integration-style test against a temp `SQLiteWikiStore`.

**NOT in scope**: toolkit integration (TASK-1936); `WikiCombinedSearch`
(exists but intentionally unused — decision); changes under
`parrot/knowledge/wiki/`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/wiki.py` | CREATE | Adapter |
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/__init__.py` | MODIFY | Export `ParrotWikiOrigin` |
| `packages/ai-parrot-tools/tests/multistoresearch/test_wiki_origin.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models import SearchOriginKind, OriginHit                # TASK-1930
from parrot_tools.multistoresearch.origins.base import SearchOrigin  # TASK-1932
# Store passed as an instance; lazy/TYPE_CHECKING import only:
# parrot.knowledge.wiki.store.BaseWikiStore / SQLiteWikiStore
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
class BaseWikiStore(ABC):                                   # line 268
    async def search_fts(self, query: str, category: Optional[str] = None,
                         limit: int = 10) -> list[dict[str, Any]]   # line 323 (abstract)
    async def search_vector(self, embedding: list[float],
                            limit: int = 10) -> list[dict[str, Any]]  # line 328 (abstract)
# Concrete: SQLiteWikiStore.search_fts (line 803), .search_vector (line 841)
# In-memory variant: parrot/knowledge/wiki/file_store.py:522 (search_fts)

# _fts_query helper exists at store.py:166 — internal to the store; do NOT call from the adapter.
```

### Does NOT Exist
- ~~`WikiStore.search(text, ...)`~~ — no text-level vector search; `search_vector` takes an **embedding**, so the vector leg REQUIRES the async `embedder` callable.
- ~~`WikiCombinedSearch` usage in this adapter~~ — exists (`wiki/search.py:32`) but rejected by decision; do not import it.
- ~~`ParrotWikiOrigin`~~ — does not exist yet; THIS task creates it.

---

## Implementation Notes

### Key Constraints
- The embedder is `Callable[[str], Awaitable[list[float]]]` (same convention
  as `WikiCombinedSearch.__init__`'s `embedder` param, `wiki/search.py:47-53`).
- Read the actual row dict keys returned by `SQLiteWikiStore.search_fts`
  (store.py:803) before writing the normalizer — do not guess key names.
- Adapters raise on backend failure; toolkit isolates (TASK-1936).
- Class docstring explains the wiki plane and both legs (surfaces via
  `list_search_origins`).

### References in Codebase
- Spec §2 adapter table (ParrotWiki row) + §7 Known Risks ("Wiki vector leg needs an embedder").
- `tests/knowledge/wiki/test_store.py` — how wiki stores are constructed/seeded in tests (fixture reference).

---

## Acceptance Criteria

- [ ] `supports_fts is True`; `fts_search` delegates to `store.search_fts` with the configured category.
- [ ] `search` uses the vector leg only when an embedder is configured; otherwise the FTS leg. Both normalize to `OriginHit` (`origin_kind == SearchOriginKind.WIKI`, 1-based `native_rank`).
- [ ] Constructing without embedder works (FTS-only origin).
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/multistoresearch/test_wiki_origin.py -v`
- [ ] `ruff check` clean on the new file.

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/multistoresearch/test_wiki_origin.py
import pytest
from parrot.models import SearchOriginKind
from parrot_tools.multistoresearch.origins import ParrotWikiOrigin

class FakeWikiStore:
    def __init__(self):
        self.fts_calls, self.vec_calls = [], []
    async def search_fts(self, query, category=None, limit=10):
        self.fts_calls.append((query, category))
        return [{"page_id": "p1", "title": "T", "content": "C", "score": 1.0}]
    async def search_vector(self, embedding, limit=10):
        self.vec_calls.append(embedding)
        return [{"page_id": "p2", "title": "V", "content": "C2", "score": 0.9}]

async def fake_embedder(text):
    return [0.1, 0.2]

async def test_search_without_embedder_uses_fts():
    store = FakeWikiStore()
    hits = await ParrotWikiOrigin(store=store).search("q", k=5)
    assert store.fts_calls and not store.vec_calls
    assert hits[0].origin_kind == SearchOriginKind.WIKI

async def test_search_with_embedder_uses_vector():
    store = FakeWikiStore()
    await ParrotWikiOrigin(store=store, embedder=fake_embedder).search("q", k=5)
    assert store.vec_calls and not store.fts_calls

async def test_fts_search_passes_category():
    store = FakeWikiStore()
    await ParrotWikiOrigin(store=store, category="docs").fts_search("q", k=5)
    assert store.fts_calls == [("q", "docs")]
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1932 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing ANY code (read the real `search_fts` row shape at store.py:803)
4. **Update status** in `sdd/tasks/index/multistoresearchtool-parrotwiki.json` → `"in-progress"`
5. **Implement**, **verify** acceptance criteria
6. **Move this file** to `sdd/tasks/completed/`, update index → `"done"`, fill Completion Note

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
