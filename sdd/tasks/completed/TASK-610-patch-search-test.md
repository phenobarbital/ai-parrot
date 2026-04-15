# TASK-610: PATCH Endpoint — Search Test

**Feature**: vectorstore-handler-api
**Spec**: `sdd/specs/vectorstore-handler-api.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-608
**Assigned-to**: unassigned

---

## Context

> Implements the PATCH method of `VectorStoreHandler` from Spec Module 4.
> Provides search testing against a vector store collection using similarity search,
> MMR search, or both. Returns results in a wrapped response format.

---

## Scope

- Implement `VectorStoreHandler.patch()`:
  - Parse JSON body: `StoreConfig` fields + `query`, `method` (similarity/mmr/both), `k` (default 5)
  - Use `_get_store(config)` to obtain a connected store instance
  - Validate collection exists (return 404 if not)
  - Execute search based on `method`:
    - `"similarity"`: call `store.similarity_search(query, table, schema, k=k)`
    - `"mmr"`: call `store.mmr_search(query, table, schema, k=k)`
    - `"both"`: call both and combine results
  - Return wrapped response: `{"query": "...", "method": "...", "count": N, "results": [...]}`
  - Serialize `SearchResult` objects to dicts
- Handle errors: missing query (400), collection not found (404), store errors (500)
- Write unit tests with mocked store

**NOT in scope**: POST (TASK-609), PUT (TASK-611), ensemble search (VectorInterface._ensemble_search is not used here — keep it simple)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/handlers/stores/handler.py` | MODIFY | Replace `patch()` stub with implementation |
| `packages/ai-parrot/tests/unit/test_vectorstore_patch.py` | CREATE | Unit tests for PATCH endpoint |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Already imported in handler.py from TASK-608:
from parrot.stores.models import StoreConfig, SearchResult
```

### Existing Signatures to Use
```python
# parrot/stores/models.py:7-18
class SearchResult(BaseModel):
    id: str                                                          # line 11
    content: str                                                     # line 12
    metadata: Dict[str, Any] = Field(default_factory=dict)           # line 13
    score: float                                                     # line 14
    ensemble_score: float = None                                     # line 15
    search_source: str = None                                        # line 16
    similarity_rank: Optional[int] = None                            # line 17
    mmr_rank: Optional[int] = None                                   # line 18

# AbstractStore search methods:
async def similarity_search(self, query, table=None, schema=None, k=None,
                             limit=None, metadata_filters=None,
                             score_threshold=None, metric=None,
                             embedding_column='embedding',
                             content_column='document',
                             metadata_column='cmetadata', id_column='id',
                             additional_columns=None) -> List[SearchResult]   # postgres.py:634

async def mmr_search(self, query, table=None, schema=None, k=10,
                      fetch_k=None, lambda_mult=0.5,
                      metadata_filters=None, score_threshold=None,
                      metric=None, ...) -> List[SearchResult]                # postgres.py:1670

async def collection_exists(self, table, schema='public') -> bool            # postgres.py:2747

# SearchResult is a Pydantic BaseModel — use .model_dump() to serialize
```

### Does NOT Exist
- ~~`store.search(query, method="similarity")`~~ — no unified search method; must call `similarity_search` or `mmr_search` explicitly
- ~~`SearchResult.to_dict()`~~ — use `.model_dump()` (Pydantic v2) or `.dict()` (Pydantic v1)
- ~~`store.test_search()`~~ — no such method

---

## Implementation Notes

### Pattern to Follow
```python
async def patch(self) -> web.Response:
    """Test search against a vector store collection."""
    try:
        body = await self.request.json()
        query = body.get('query')
        if not query:
            return self.json_response({"error": "Missing required field: query"}, status=400)

        table = body.get('table')
        schema = body.get('schema', 'public')
        method = body.get('method', 'similarity')  # similarity, mmr, both
        k = body.get('k', 5)

        config = StoreConfig(...)
        store = await self._get_store(config)

        if not await store.collection_exists(table=table, schema=schema):
            return self.json_response(
                {"error": f"Collection '{schema}.{table}' not found"},
                status=404
            )

        results = []
        if method in ('similarity', 'both'):
            sim_results = await store.similarity_search(
                query=query, table=table, schema=schema, k=k
            )
            results.extend(sim_results)
        if method in ('mmr', 'both'):
            mmr_results = await store.mmr_search(
                query=query, table=table, schema=schema, k=k
            )
            if method == 'mmr':
                results = mmr_results
            else:
                results.extend(mmr_results)

        # Serialize SearchResult objects
        serialized = [r.model_dump() for r in results]

        return self.json_response({
            "query": query,
            "method": method,
            "count": len(serialized),
            "results": serialized
        })
    except Exception as err:
        self.logger.error(f"PATCH error: {err}", exc_info=True)
        return self.json_response({"error": str(err)}, status=500)
```

### Key Constraints
- `method` must be one of: `"similarity"`, `"mmr"`, `"both"` — return 400 for invalid
- For BigQuery: `collection_exists` and search methods use `dataset` param, not `schema` — this is handled by `_get_store` mapping, but the search call params need store-aware handling
- Use `json_encoder` from `datamodel.parsers.json` if `model_dump()` produces non-JSON-serializable types
- When `method="both"`, combine results but don't deduplicate (simple concatenation is fine for testing)

### References in Codebase
- `packages/ai-parrot/src/parrot/interfaces/vector.py:110-153` — ensemble search pattern (for reference only, not required here)

---

## Acceptance Criteria

- [ ] PATCH with `method=similarity` returns similarity search results
- [ ] PATCH with `method=mmr` returns MMR search results
- [ ] PATCH with `method=both` returns combined results
- [ ] Returns 400 for missing `query`
- [ ] Returns 400 for invalid `method` value
- [ ] Returns 404 when collection doesn't exist
- [ ] Response format: `{"query": "...", "method": "...", "count": N, "results": [...]}`
- [ ] Results are serialized SearchResult dicts
- [ ] All unit tests pass

---

## Test Specification

```python
# tests/unit/test_vectorstore_patch.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.stores.models import SearchResult


class TestPatchSearchTest:
    @pytest.mark.asyncio
    async def test_similarity_search(self):
        """Returns similarity search results."""
        pass  # mock store.similarity_search, verify response wrapper

    @pytest.mark.asyncio
    async def test_mmr_search(self):
        """Returns MMR search results."""
        pass

    @pytest.mark.asyncio
    async def test_both_search(self):
        """Returns combined similarity + MMR results."""
        pass

    @pytest.mark.asyncio
    async def test_missing_query_returns_400(self):
        """Returns 400 when query is missing."""
        pass

    @pytest.mark.asyncio
    async def test_invalid_method_returns_400(self):
        """Returns 400 for invalid method value."""
        pass

    @pytest.mark.asyncio
    async def test_collection_not_found_returns_404(self):
        """Returns 404 when collection doesn't exist."""
        pass

    @pytest.mark.asyncio
    async def test_empty_results(self):
        """Returns 200 with empty results, not an error."""
        pass
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-608 is in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-610-patch-search-test.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (claude-sonnet)
**Date**: 2026-04-07
**Notes**: PATCH method implemented in TASK-608. Created 7 unit tests covering all acceptance criteria. All pass.

**Deviations from spec**: Implementation was committed as part of TASK-608 handler.py.
