# TASK-1933: `PageIndexOrigin` adapter (mode: vector | hybrid | llm)

**Feature**: FEAT-379 — MultiStoreSearch Toolkit with PageIndex, GraphIndex & ParrotWiki Origins
**Spec**: `sdd/specs/multistoresearchtool-parrotwiki.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1932
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 4: the PageIndex origin adapter. PageIndex is
vectorless, tree-based reasoning RAG with three retrieval backends; the
adapter exposes them behind one `mode` switch. Resolved decisions: mode is
configurable `vector | hybrid | llm`, **default `hybrid`**; the sync
vector-walk path must never block the event loop.

---

## Scope

- Implement `PageIndexOrigin(SearchOrigin)` in
  `parrot_tools/multistoresearch/origins/pageindex.py`.
- Constructor: the backend object(s) for the chosen mode, `mode: str = "hybrid"`
  (validate against {"vector", "hybrid", "llm"}), `name: str = "pageindex"`,
  `description` (default explains tree-based retrieval + mode), optional `timeout`.
- Mode dispatch:
  - `hybrid` → `await HybridPageIndexSearch.search(query, top_k=k)` — result
    dicts carry `node_id`, `title`, `summary`, …
  - `llm` → `await PageIndexRetriever.search(query)` → `TreeSearchResult`;
    docstring must warn this mode spends LLM tokens per call.
  - `vector` → `FlatMatrixSearch.search(...)` is **SYNC** — run it via
    `loop.run_in_executor` (this internal offload is the ONE sanctioned
    exception to the no-`to_thread` decision, which governs `batch_search`
    semantics, not sync-backend wrapping; see spec §7 Known Risks).
- Normalize each mode's native results into `list[OriginHit]` (content from
  node title+summary or equivalent, metadata carries `node_id`/`tree` info,
  1-based `native_rank`).
- `supports_fts = False`.
- Unit tests with fake backends for all three modes; an event-loop
  responsiveness test for `vector` mode.

**NOT in scope**: toolkit integration (TASK-1936); changes under
`parrot/knowledge/pageindex/` (read-only consumption).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/pageindex.py` | CREATE | Adapter |
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/__init__.py` | MODIFY | Export `PageIndexOrigin` |
| `packages/ai-parrot-tools/tests/multistoresearch/test_pageindex_origin.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models import SearchOriginKind, OriginHit                       # TASK-1930
from parrot_tools.multistoresearch.origins.base import SearchOrigin         # TASK-1932
# Backends are passed in as instances — import them lazily/TYPE_CHECKING only:
# parrot.knowledge.pageindex.retriever.PageIndexRetriever
# parrot.knowledge.pageindex.hybrid_search.HybridPageIndexSearch
# parrot.knowledge.pageindex.vector_walk.FlatMatrixSearch
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/retriever.py
class PageIndexRetriever:                                  # line 11
    async def search(self, query: str) -> TreeSearchResult  # line 38 — LLM tree search, token-spending

# packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py
class HybridPageIndexSearch:                               # line 52
    async def search(self, query: str, top_k: int = 10, use_bm25: bool = True,
                     use_llm_walk: bool = True, use_vec: bool = False,
                     use_embedding_walk: Optional[bool] = None,
                     rerank: bool = False) -> list[dict[str, Any]]  # line 288
    # result dicts: node_id, title, summary, ...

# packages/ai-parrot/src/parrot/knowledge/pageindex/vector_walk.py
class FlatMatrixSearch:                                    # line 36
    def search(self, ...)                                  # line 60 — SYNC. Executor-wrap. Read the
    # full signature in the file before implementing the vector mode.
```

### Does NOT Exist
- ~~`HybridPageIndexSearch.asearch` / `FlatMatrixSearch.async_search`~~ — no async variant of the vector walk exists; executor-wrap the sync `search`.
- ~~`PageIndexOrigin`~~ — does not exist yet; THIS task creates it.
- ~~a common result model across the three PageIndex backends~~ — each mode returns a different shape (`TreeSearchResult`, `list[dict]`, `FlatMatrixSearch` output); read each before normalizing. Verify `TreeSearchResult` fields in `parrot/knowledge/pageindex/` before use.

---

## Implementation Notes

### Key Constraints
- Mode validation raises `ValueError` at construction, not at search time.
- Default mode `hybrid` (resolved decision — assert in tests).
- Adapters raise on backend failure; the toolkit (TASK-1936) isolates.
- Google-style docstrings; the class docstring explains the three modes and
  their cost profiles (this text surfaces via `list_search_origins`).

### References in Codebase
- Spec §2 adapter table (PageIndex row) + §7 Known Risks (sync walk, LLM cost).
- `packages/ai-parrot/tests/knowledge/pageindex/e2e_pdf_test.py` — how PageIndex backends are constructed in tests (fixture reference).

---

## Acceptance Criteria

- [ ] `PageIndexOrigin(backend..., mode=...)` validates mode; default is `hybrid`.
- [ ] All three modes normalize to `list[OriginHit]` with 1-based `native_rank` and `origin_kind == SearchOriginKind.PAGEINDEX`.
- [ ] `vector` mode does not block the event loop (test: concurrent `asyncio.sleep(0)` task makes progress while a slow fake sync search runs in executor).
- [ ] `supports_fts is False`.
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/multistoresearch/test_pageindex_origin.py -v`
- [ ] `ruff check` clean on the new file.

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/multistoresearch/test_pageindex_origin.py
import asyncio
import pytest
from parrot.models import SearchOriginKind
from parrot_tools.multistoresearch.origins import PageIndexOrigin

class FakeHybrid:
    async def search(self, query, top_k=10, **kw):
        return [{"node_id": "n1", "title": "T", "summary": "S"}]

def test_default_mode_is_hybrid():
    origin = PageIndexOrigin(hybrid=FakeHybrid())
    assert origin.mode == "hybrid"

def test_invalid_mode_rejected():
    with pytest.raises(ValueError):
        PageIndexOrigin(hybrid=FakeHybrid(), mode="quantum")

async def test_hybrid_mode_normalizes():
    hits = await PageIndexOrigin(hybrid=FakeHybrid()).search("q", k=5)
    assert hits[0].origin_kind == SearchOriginKind.PAGEINDEX
    assert hits[0].native_rank == 1

async def test_vector_mode_offloaded():
    # slow SYNC backend must not freeze the loop
    ...
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1932 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing ANY code (read `FlatMatrixSearch.search`'s full signature and `TreeSearchResult`'s fields first)
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
