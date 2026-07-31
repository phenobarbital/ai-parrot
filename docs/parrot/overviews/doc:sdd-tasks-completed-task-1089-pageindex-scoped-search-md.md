---
type: Wiki Overview
title: 'TASK-1089: PageIndexToolkit.search_documents_scoped'
id: doc:sdd-tasks-completed-task-1089-pageindex-scoped-search-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'from parrot.tools.pageindex_toolkit import PageIndexToolkit # verified:
  pageindex_toolkit.py:39'
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.tools
  rel: mentions
- concept: mod:parrot.tools.decorators
  rel: mentions
---

# TASK-1089: PageIndexToolkit.search_documents_scoped

**Feature**: FEAT-159 — Concept-Document Authority Layer
**Spec**: `sdd/specs/concept-document-authority.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> Module 6 of the spec. Adds a new `search_documents_scoped` method to `PageIndexToolkit`
> that searches a SUBSET of indexed PageIndex trees rather than the full collection.
> This is the tool invoked by the `authoritative_doc_for_topic` traversal's `tool_call`
> post-action via FEAT-158's `ToolCallDispatcher`.

---

## Scope

- Add to `packages/ai-parrot/src/parrot/tools/pageindex_toolkit.py`:
  - `SearchScopedInput` pydantic model with `tree_ids: list[str]`, `query: str`, `include_tree_context: bool`, `max_trees: int = 10`.
  - `search_documents_scoped(tree_ids, query, include_tree_context, max_trees)` async method decorated with `@tool_schema(SearchScopedInput)`.
  - Iterates over `self._indices.get(tree_id)` for each tree_id (up to `max_trees`).
  - Calls existing `retriever.search(query)` + `retriever.retrieve(query)` per tree.
  - Silently skips missing tree_ids with a WARNING log.
  - Returns `{"status": "ok"|"empty", "scoped_results": [...]}`.
  - Each result: `{"tree_id": str, "doc_name": str|None, "node_list": list, "thinking": str, "context": str}`.
- Write unit tests.

**NOT in scope**: Modifying `search_documents` (existing method), the traversal YAML (TASK-1084), the degradation chain (TASK-1090).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/pageindex_toolkit.py` | MODIFY | Add SearchScopedInput + search_documents_scoped method |
| `packages/ai-parrot/tests/tools/test_pageindex_scoped.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.pageindex_toolkit import PageIndexToolkit  # verified: pageindex_toolkit.py:39
from parrot.tools.decorators import tool_schema  # verified: decorators.py:37
from parrot.pageindex.retriever import PageIndexRetriever  # verified: retriever.py:11
from pydantic import BaseModel, Field, ConfigDict
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/pageindex_toolkit.py:39
class PageIndexToolkit(AbstractToolkit):
    name = "pageindex"                                    # line 42
    tool_prefix: str = "pageindex"                        # line 43
    _indices: dict[str, dict[str, Any]] = {}              # line 63
    # Structure: {index_id: {"tree": <tree>, "retriever": PageIndexRetriever}}

    @tool_schema(SearchDocumentsInput)
    async def search_documents(
        self,
        index_id: str,
        query: str,
        include_tree_context: bool = False,
    ) -> dict[str, Any]:                                  # line 114
        # Existing single-tree search — DO NOT modify this method.

# packages/ai-parrot/src/parrot/pageindex/retriever.py:11
class PageIndexRetriever:
    async def search(self, query: str) -> TreeSearchResult:  # line 38
    async def retrieve(
        self,
        query: str,
        pdf_pages: Optional[list[tuple[str, int]]] = None,
    ) -> str:                                              # line 81
```

### Does NOT Exist
- ~~`PageIndexToolkit.search_documents_scoped`~~ — does NOT exist; this task creates it
- ~~`PageIndexToolkit.search_documents` accepting `tree_ids` list~~ — takes single `index_id`; do NOT modify
- ~~A `max_trees` parameter anywhere in PageIndex~~ — introduced by this task on `SearchScopedInput`

---

## Implementation Notes

### Pattern to Follow
Follow the existing `search_documents` method as the template:
```python
class SearchScopedInput(BaseModel):
    tree_ids: list[str] = Field(..., description="PageIndex tree IDs to scope the search to")
    query: str = Field(..., min_length=1, description="Free-form natural-language query")
    include_tree_context: bool = Field(default=False, description="Include per-tree tree_context blob")
    max_trees: int = Field(default=10, ge=1, le=20, description="Hard cap on trees to search")
    model_config = ConfigDict(extra="forbid")

@tool_schema(SearchScopedInput)
async def search_documents_scoped(
    self,
    tree_ids: list[str],
    query: str,
    include_tree_context: bool = False,
    max_trees: int = 10,
) -> dict[str, Any]:
    if not tree_ids:
        return {"status": "empty", "scoped_results": []}

    effective_ids = tree_ids[:max_trees]
    if len(tree_ids) > max_trees:
        self.logger.debug("Capped tree_ids from %d to %d", len(tree_ids), max_trees)

    scoped_results = []
    for tid in effective_ids:
        entry = self._indices.get(tid)
        if entry is None:
            self.logger.warning("tree_id '%s' not found in _indices, skipping", tid)
            continue
        retriever = entry["retriever"]
        search_result = await retriever.search(query)
        context = await retriever.retrieve(query)
        result = {
            "tree_id": tid,
            "doc_name": entry.get("name"),  # verify actual key
            "node_list": search_result.node_list if hasattr(search_result, 'node_list') else [],
            "thinking": search_result.thinking if hasattr(search_result, 'thinking') else "",
            "context": context,
        }
        if include_tree_context:
            result["tree_context"] = entry.get("tree_context")
        scoped_results.append(result)

    return {
        "status": "ok" if scoped_results else "empty",
        "scoped_results": scoped_results,
    }
```

### Key Constraints
- **Do NOT modify `search_documents`** — `search_documents_scoped` is a separate method.
- **Silent skip** for missing tree_ids: log WARNING, do not raise.
- **Max trees cap**: default 10, field on SearchScopedInput. This limits LLM cost (each tree's `search()` is LLM-backed).
- **Verify `TreeSearchResult` attributes**: check what `retriever.search()` returns to confirm `node_list` and `thinking` attribute names.
- Logger: use `self.logger` (inherited from `AbstractToolkit`).

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/pageindex_toolkit.py:114` — existing `search_documents` to follow as pattern
- `packages/ai-parrot/src/parrot/pageindex/retriever.py` — `PageIndexRetriever.search()` and `.retrieve()`

---

## Acceptance Criteria

- [ ] `SearchScopedInput` pydantic model exists with `tree_ids`, `query`, `include_tree_context`, `max_trees`
- [ ] `search_documents_scoped` exists as a `@tool_schema` decorated method on `PageIndexToolkit`
- [ ] Two of three tree_ids requested → only those two get `search()`+`retrieve()` invoked
- [ ] Missing tree_id → silently skipped with WARNING log
- [ ] Empty `tree_ids=[]` → `{"status": "empty", "scoped_results": []}` without invoking PageIndex
- [ ] `include_tree_context=True` → each result includes `tree_context`
- [ ] `max_trees` caps the number of trees searched (default 10)
- [ ] All tests pass: `pytest packages/ai-parrot/tests/tools/test_pageindex_scoped.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/tools/pageindex_toolkit.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/test_pageindex_scoped.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.tools.pageindex_toolkit import PageIndexToolkit, SearchScopedInput


class TestSearchDocumentsScoped:
    @pytest.fixture
    def toolkit_with_indices(self):
        """PageIndexToolkit with 3 mock trees in _indices."""
        tk = PageIndexToolkit.__new__(PageIndexToolkit)
        tk._indices = {}
        for tid in ["tree_a", "tree_b", "tree_c"]:
            mock_retriever = AsyncMock()
            mock_retriever.search.return_value = MagicMock(node_list=[f"node_{tid}"], thinking=f"think_{tid}")
            mock_retriever.retrieve.return_value = f"context_{tid}"
            tk._indices[tid] = {"retriever": mock_retriever, "name": f"doc_{tid}"}
        tk.logger = MagicMock()
        return tk

    async def test_basic_scoped_search(self, toolkit_with_indices):
        """Call with two tree_ids → only those two searched."""
        result = await toolkit_with_indices.search_documents_scoped(
            tree_ids=["tree_a", "tree_b"], query="test", include_tree_context=False
        )
        assert result["status"] == "ok"
        assert len(result["scoped_results"]) == 2

    async def test_missing_tree_silent_skip(self, toolkit_with_indices):
        """Missing tree_id → skipped, warning logged."""
        result = await toolkit_with_indices.search_documents_scoped(
            tree_ids=["tree_a", "ghost"], query="test"
        )
        assert len(result["scoped_results"]) == 1
        toolkit_with_indices.logger.warning.assert_called()

    async def test_empty_tree_ids(self, toolkit_with_indices):
        """Empty list → status=empty, no PageIndex calls."""
        result = await toolkit_with_indices.search_documents_scoped(
            tree_ids=[], query="test"
        )
        assert result == {"status": "empty", "scoped_results": []}

    async def test_include_tree_context(self, toolkit_with_indices):
        """include_tree_context=True → tree_context in results."""
        ...

    async def test_max_trees_cap(self, toolkit_with_indices):
        """More tree_ids than max_trees → only first max_trees searched."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — this task has no dependencies
3. **Verify the Codebase Contract** — before writing ANY code:
   - Read `pageindex_toolkit.py` to confirm `_indices` structure and `search_documents` pattern
   - Read `retriever.py` to confirm `TreeSearchResult` attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/concept-document-authority.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1089-pageindex-scoped-search.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
