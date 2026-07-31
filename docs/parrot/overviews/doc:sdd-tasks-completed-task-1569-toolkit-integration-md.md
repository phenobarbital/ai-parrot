---
type: Wiki Overview
title: 'TASK-1569: Toolkit Integration — search_with_expansion Tool'
id: doc:sdd-tasks-completed-task-1569-toolkit-integration-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'The final integration step: expose the `GraphExpandedRetriever` as a new
  tool'
relates_to:
- concept: mod:parrot.knowledge.graphindex.retriever
  rel: mentions
- concept: mod:parrot_tools.graphindex.toolkit
  rel: mentions
---

# TASK-1569: Toolkit Integration — search_with_expansion Tool

**Feature**: FEAT-217 — Graph-Expanded Retrieval Pipeline
**Spec**: `sdd/specs/FEAT-217-graph-expanded-retrieval.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1568
**Assigned-to**: unassigned

---

## Context

The final integration step: expose the `GraphExpandedRetriever` as a new tool
on `GraphIndexToolkit` so LLM agents can use graph-expanded retrieval via the
existing tool interface.

Implements spec Section 3 (Module 5: Toolkit Integration).

---

## Scope

- Add `search_with_expansion()` async method to `GraphIndexToolkit`
- The method creates a `GraphExpandedRetriever` from the toolkit's existing components and calls `search()`
- Returns the result as a serializable dict (`.model_dump()` on `GraphRetrievalResult`)
- Register the method as a tool (following existing toolkit tool patterns)

**NOT in scope**: Modifying the retriever itself (complete in TASK-1565–1568)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py` | MODIFY | Add `search_with_expansion()` tool method |
| `packages/ai-parrot-tools/tests/graphindex/test_toolkit.py` | MODIFY | Add integration test |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Use these exact imports and signatures. Do not guess alternatives.

### Verified Imports

```python
# verified: packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py:60
from parrot_tools.graphindex.toolkit import GraphIndexToolkit

# From TASK-1565-1568 (created in prior tasks)
from parrot.knowledge.graphindex.retriever import (
    GraphExpandedRetriever, ExpansionConfig, BudgetConfig, GraphRetrievalResult,
)
```

### Existing Signatures to Use

```python
# packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py:60
class GraphIndexToolkit(AbstractToolkit):
    def __init__(
        self,
        graph: rustworkx.PyDiGraph,        # line 92
        faiss_index: faiss.Index,           # line 93
        node_map: dict[str, int],           # line 94
        node_id_list: list[str],            # line 95
        client=None,                        # line 96
        assembler=None,                     # line 97
        embedder=None,                      # line 98 — GraphIndexEmbedder or None
        nodes=None,                         # line 99 — list[UniversalNode] or None
        signal_config=None,                 # line 100 — SignalRelevanceConfig or None
    ) -> None:
        # self.graph, self.embedder, self.nodes, self.signal_config
        # are all stored as instance attributes
```

### Does NOT Exist

- ~~`GraphIndexToolkit.search_with_expansion()`~~ — this task creates it
- ~~`GraphIndexToolkit.retriever`~~ — no stored retriever; create on-demand in the tool method
- ~~`GraphIndexToolkit.communities`~~ — toolkit does not currently hold CommunitiesResult; either add as optional init param or omit community annotation from toolkit path

---

## Implementation Notes

### Tool Method Pattern

Follow existing tool methods in the toolkit. The toolkit already has `self.graph`,
`self.embedder`, `self.nodes`, and `self.signal_config` — construct a
`GraphExpandedRetriever` from these.

```python
async def search_with_expansion(
    self,
    query: str,
    seed_top_k: int = 10,
    max_hops: int = 2,
    decay_base: float = 0.7,
    max_tokens: int = 8000,
) -> dict:
    """Search with graph-expanded retrieval: seeds → graph expansion → result assembly.
    
    Args:
        query: Natural language search query.
        seed_top_k: Number of seed nodes from initial search.
        max_hops: Maximum graph traversal depth (1-4).
        decay_base: Score decay per hop (0-1, default 0.7).
        max_tokens: Token budget for results.
    
    Returns:
        Dictionary with ranked nodes and retrieval metadata.
    """
    retriever = GraphExpandedRetriever(
        graph=self.graph,
        nodes=self.nodes,
        embedder=self.embedder,
        signal_config=self.signal_config,
    )
    expansion = ExpansionConfig(max_hops=max_hops, decay_base=decay_base)
    budget = BudgetConfig(max_tokens=max_tokens)
    result = await retriever.search(query, seed_top_k=seed_top_k, expansion=expansion, budget=budget)
    return result.model_dump()
```

### Key Constraints
- Method must be `async` (calls async `retriever.search()`)
- Return a plain dict (`.model_dump()`), not a Pydantic model — tools must return JSON-serializable data
- The toolkit may not have `hybrid_search` available (it's PageIndex-specific); pass only `embedder`
- `communities` may not be available on the toolkit — the retriever handles `None` gracefully (Phase 3 skips)
- Check how existing tools are registered in this toolkit (decorator or `get_tools()` method)

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py` — existing tool methods for pattern reference

---

## Acceptance Criteria

- [ ] `search_with_expansion()` method added to `GraphIndexToolkit`
- [ ] Method creates `GraphExpandedRetriever` from toolkit's stored components
- [ ] Returns dict from `GraphRetrievalResult.model_dump()`
- [ ] Tool auto-registered (visible in toolkit's tool list)
- [ ] Parameters have sensible defaults and docstring for LLM consumption
- [ ] Integration test passes: `pytest packages/ai-parrot-tools/tests/graphindex/test_toolkit.py -v -k "search_with_expansion"`
- [ ] No linting errors

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/graphindex/test_toolkit.py (append)
import pytest
from unittest.mock import AsyncMock, MagicMock


class TestSearchWithExpansion:
    @pytest.mark.asyncio
    async def test_toolkit_search_with_expansion(self):
        """Toolkit tool returns GraphRetrievalResult dict."""
        # Setup: create a GraphIndexToolkit with mocked components
        # Call search_with_expansion("test query")
        # Assert: result is a dict with expected keys (query, nodes, truncated, etc.)
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/FEAT-217-graph-expanded-retrieval.spec.md` for full context
2. **Check dependencies** — verify TASK-1565–1568 are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — read `toolkit.py` to confirm current tool registration pattern
4. **Update status** in `sdd/tasks/index/FEAT-217-graph-expanded-retrieval.json` → `"in-progress"`
5. **Implement** following the scope and codebase contract above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1569-toolkit-integration.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: 
