# TASK-5315: HybridPageIndexSearch accepts no adapter

**Feature**: FEAT-842 — PageIndex Local MCP Toolkit
**Spec**: `sdd/specs/pageindex-local-mcp-toolkit.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements the `hybrid_search.py` half of spec §3 **Module 2** (deterministic
degradation). The toolkit never asks the engine for the LLM walk when it has no adapter
(TASK-5314), but the engine's own type says the adapter is required and `_llm_rank`
dereferences `self._adapter.model`. This task makes `adapter` optional and makes
`_llm_rank` fail with a clear `ValueError` instead of an `AttributeError` — defence in depth.

---

## Scope

- Change `HybridPageIndexSearch.__init__`'s `adapter: PageIndexLLMAdapter,` to
  `adapter: Optional[PageIndexLLMAdapter] = None,` (it stays the second parameter).
- At the top of `_llm_rank`, raise
  `ValueError("LLM walk requested but no LLM is configured for this toolkit")` when
  `self._adapter is None`.
- Extend `tests/knowledge/pageindex/test_hybrid_search.py` with two tests (AC-5).

**NOT in scope**: `toolkit.py` (TASK-5314); `retriever.py` (spec: no change —
`PageIndexRetriever` is only built by `_llm_rank` and `search_documents_scoped`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py` | MODIFY | optional adapter, `_llm_rank` guard |
| `packages/ai-parrot/tests/knowledge/pageindex/test_hybrid_search.py` | MODIFY | two new tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` @ `1db2685b95`. Paths relative to `packages/ai-parrot/src/parrot/`.

### Verified Imports
```python
from parrot.knowledge.pageindex.hybrid_search import HybridPageIndexSearch   # hybrid_search.py (class, __init__ at :73)
# hybrid_search.py already imports: `from typing import TYPE_CHECKING, Any, Callable, Optional` (:24)
# and `from .llm_adapter import PageIndexLLMAdapter` (:29); `from __future__ import annotations` (:20)
```

### Existing Signatures to Use
```python
# knowledge/pageindex/hybrid_search.py
class HybridPageIndexSearch:
    def __init__(self, tree: dict[str, Any], adapter: PageIndexLLMAdapter, reranker=None, model=None,
                 default_bm25_k=20, content_loader=None, embedding_store=None, embed_fn=None,
                 use_vec_rank=False, use_embedding_walk=False, *, tree_name=None, generation_id=0)  # :73-90; adapter line :76
        self._adapter = adapter                                                  # :90
    async def _llm_rank(self, query: str) -> list[str]:                         # :284
        retriever = PageIndexRetriever(tree=self._tree, adapter=self._adapter,
                                       model=self._model or self._adapter.model)   # :285-289
    async def search(self, query, top_k, use_bm25=True, use_llm_walk=True, rerank=False, use_vec=False, ...)  # :307
        # raises ValueError("At least one of use_bm25 / use_llm_walk / ...") when every signal is off   # :348

# tests/knowledge/pageindex/test_hybrid_search.py
def _fixture_tree() -> dict                                   # :13
def _adapter() -> MagicMock                                   # :44
async def test_bm25_only_returns_lexical_matches()            # :52 — query "late fee payment", expects node "0001" in top 2
```

### Does NOT Exist
- ~~`HybridPageIndexSearch.has_llm`~~ — not added; the toolkit owns `has_llm`
- ~~a `NoLLMError` exception class~~ — use plain `ValueError` with the spec's text

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/pageindex/test_hybrid_search.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py#HybridPageIndexSearch",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py#HybridPageIndexSearch.__init__",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py#HybridPageIndexSearch._llm_rank"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Make `adapter` optional — *why*: the toolkit builds the engine with `adapter=None` when no model is configured.
2. Guard `_llm_rank` — *why*: a clear error beats `AttributeError: 'NoneType' object has no attribute 'model'`.
3. Add the tests — *why*: AC-5.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '        adapter: PageIndexLLMAdapter,' hybrid_search.py)
# REPLACE (hybrid_search.py:76) with:
        adapter: Optional[PageIndexLLMAdapter] = None,

# occurrences: 1 (verified: grep -cF '    async def _llm_rank(self, query: str) -> list[str]:' hybrid_search.py)
# AFTER — insert below `    async def _llm_rank(self, query: str) -> list[str]:` (verified: hybrid_search.py:284)
        if self._adapter is None:
            raise ValueError("LLM walk requested but no LLM is configured for this toolkit")
```
**Why**: `tree` keeps no default, so the new default on the second parameter is legal and
every existing positional/keyword call is unchanged. The message text is the same one the
toolkit raises, so an operator sees one wording whichever layer catches it. If the class
docstring documents `adapter` as required, update that line to say it is optional and
only needed for the LLM walk.

### `packages/ai-parrot/tests/knowledge/pageindex/test_hybrid_search.py` (MODIFY)
```python
# APPEND at end of file
@pytest.mark.asyncio
async def test_bm25_without_adapter() -> None:
    """FEAT-842 AC-5: an engine with no adapter still searches with BM25."""
    # FILL IN: HybridPageIndexSearch(tree=_fixture_tree(), adapter=None, default_bm25_k=5);
    #   search("late fee payment", top_k=3, use_bm25=True, use_llm_walk=False) -> results[0]["source"] == "bm25"


@pytest.mark.asyncio
async def test_llm_rank_without_adapter_raises() -> None:
    """FEAT-842 AC-5."""
    # FILL IN: pytest.raises(ValueError, match="no LLM is configured") around engine._llm_rank("anything")
```
**Why**: mirrors `test_bm25_only_returns_lexical_matches` (:52) so the fixture tree and
query are already known to hit. Check whether the existing tests need
`@pytest.mark.asyncio` (the file uses it at :50) and match that style.

### FILL IN checklist
- [ ] two test bodies — bounded by AC-5
- [ ] class docstring wording for `adapter`, if it states "required" — bounded by spec §3 M2

---

## Acceptance Criteria

- [ ] AC-5 `HybridPageIndexSearch(tree, adapter=None, ...)` searches with BM25; `_llm_rank` raises `ValueError`.
- [ ] All existing tests in `test_hybrid_search.py` still pass.
- [ ] `ruff check` clean on both files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_hybrid_search.py -q`

---

## Test Specification

See the MODIFY block for `test_hybrid_search.py` above.

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug pageindex-local-mcp-toolkit --feature-id FEAT-842`).
2. Verify the anchors with `grep -cF`; mark `in-progress` in the per-spec index and commit only the index.
3. Implement from the blueprint; run the Validation Command with `PYTHONPATH=packages/ai-parrot/src`.
4. Commit the two files; `parrot sdd task close TASK-5315 pageindex-local-mcp-toolkit verified`; fill the Completion Note; commit the SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
