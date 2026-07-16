---
type: Wiki Overview
title: 'TASK-1631: Combined Search'
id: doc:sdd-tasks-completed-task-1631-combined-search-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements unified search across PageIndex trees and GraphIndex graph. Merges
relates_to:
- concept: mod:parrot.knowledge.wiki.models
  rel: mentions
- concept: mod:parrot.knowledge.wiki.search
  rel: mentions
---

# TASK-1631: Combined Search

**Feature**: FEAT-260 — LLM Wiki: Persistent Knowledge Base with PageIndex + GraphIndex
**Spec**: `sdd/specs/llmwiki-pageindex-graphindex.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1627
**Assigned-to**: unassigned

---

## Context

Implements unified search across PageIndex trees and GraphIndex graph. Merges
results from `HybridPageIndexSearch` (BM25 + LLM walk) and
`GraphExpandedRetriever` (seed → expand → community → assemble), normalizes
scores, applies configurable weights, and returns unified `WikiSearchResult`
list. Implements Spec §3 Module 5.

---

## Scope

- Implement `WikiCombinedSearch` class with:
  - `search(query, mode, top_k, weights) -> list[WikiSearchResult]` — unified
    search across both indexes
  - `_search_pageindex(query, top_k) -> list[WikiSearchResult]` — delegate to
    PageIndexToolkit.search()
  - `_search_graphindex(query, top_k) -> list[WikiSearchResult]` — delegate to
    GraphIndexToolkit.search_hybrid()
  - `_merge_results(pi_results, gi_results, weights) -> list[WikiSearchResult]`
    — normalize scores to [0,1], apply weights, deduplicate, sort
  - `find_related(page_id, depth) -> list[dict]` — graph-based related page
    discovery via GraphIndexToolkit.get_neighborhood()
- Support mode parameter: "pageindex" | "graphindex" | "combined" (default)
- Write unit tests

**NOT in scope**: Reranker integration (can be added later), toolkit wiring (TASK-1633)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/search.py` | CREATE | WikiCombinedSearch |
| `tests/knowledge/wiki/test_search.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.wiki.models import WikiSearchResult  # from TASK-1627
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py
class PageIndexToolkit(AbstractToolkit):  # line 50
    async def search(self, tree_name: str, query: str, top_k: int = 10,
                     use_bm25: bool = True, use_llm_walk: bool = True,
                     rerank: bool = False, categories: Optional[list[str]] = None,
                     metadata_filter: Optional[dict] = None) -> list[dict]:  # line 414

# packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py
class GraphIndexToolkit(AbstractToolkit):  # line 63
    async def search_hybrid(self, query: str, top_k: int = 10) -> list[dict]:  # line 307
    async def get_neighborhood(self, node_id: str, depth: int = 2) -> dict:  # line 234
```

### Does NOT Exist

- ~~`parrot.knowledge.wiki.search`~~ — does not exist yet; this task creates it
- ~~`WikiCombinedSearch`~~ — does not exist yet
- ~~`PageIndexToolkit.combined_search`~~ — no such method; use `.search()`
- ~~`GraphIndexToolkit.search`~~ — method is `search_hybrid`, not `search`

---

## Implementation Notes

### Pattern to Follow

```python
class WikiCombinedSearch:
    def __init__(
        self,
        pageindex_toolkit: PageIndexToolkit,
        graphindex_toolkit: GraphIndexToolkit,
        default_weights: Optional[dict[str, float]] = None,
    ) -> None:
        self._pi = pageindex_toolkit
        self._gi = graphindex_toolkit
        self._weights = default_weights or {"pageindex": 0.6, "graphindex": 0.4}
        self.logger = logging.getLogger(__name__)
```

### Key Constraints

- Score normalization: min-max scale each source's scores to [0, 1] before weighting
- Deduplication: if same content appears in both indexes, keep highest-scored
- Async throughout — both search calls can be awaited concurrently via asyncio.gather
- Return empty list if no results, not None

---

## Acceptance Criteria

- [ ] Combined search merges results from both indexes
- [ ] Score normalization produces values in [0, 1]
- [ ] Mode filter works for "pageindex" / "graphindex" / "combined"
- [ ] `find_related` returns graph neighborhood
- [ ] All tests pass: `pytest tests/knowledge/wiki/test_search.py -v`

---

## Test Specification

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.knowledge.wiki.search import WikiCombinedSearch
from parrot.knowledge.wiki.models import WikiSearchResult

@pytest.fixture
def mock_pi():
    pi = MagicMock()
    pi.search = AsyncMock(return_value=[
        {"node_id": "n1", "title": "Page 1", "score": 0.9, "summary": "..."},
    ])
    return pi

@pytest.fixture
def mock_gi():
    gi = MagicMock()
    gi.search_hybrid = AsyncMock(return_value=[
        {"node_id": "n2", "title": "Node 2", "score": 0.8, "summary": "..."},
    ])
    return gi

class TestWikiCombinedSearch:
    @pytest.mark.asyncio
    async def test_combined_search(self, mock_pi, mock_gi):
        cs = WikiCombinedSearch(mock_pi, mock_gi)
        results = await cs.search("neural networks", mode="combined")
        assert len(results) == 2
        assert all(isinstance(r, WikiSearchResult) for r in results)

    @pytest.mark.asyncio
    async def test_pageindex_only(self, mock_pi, mock_gi):
        cs = WikiCombinedSearch(mock_pi, mock_gi)
        results = await cs.search("test", mode="pageindex")
        mock_gi.search_hybrid.assert_not_called()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/llmwiki-pageindex-graphindex.spec.md` §3 Module 5
2. **Check dependencies** — TASK-1627 must be completed
3. **Read** `pageindex/toolkit.py:414` and `graphindex/toolkit.py:307` for search APIs
4. **Implement** WikiCombinedSearch with score normalization and mode filtering
5. **Verify** all acceptance criteria

---

## Completion Note

*(Agent fills this in when done)*
