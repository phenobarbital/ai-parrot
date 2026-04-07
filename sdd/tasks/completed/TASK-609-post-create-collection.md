# TASK-609: POST Endpoint — Create Collection

**Feature**: vectorstore-handler-api
**Spec**: `sdd/specs/vectorstore-handler-api.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-608
**Assigned-to**: unassigned

---

## Context

> Implements the POST method of `VectorStoreHandler` from Spec Module 4.
> Creates or prepares a vector store collection based on a `StoreConfig` payload.
> Replaces the POST stub from TASK-608.

---

## Scope

- Implement `VectorStoreHandler.post()`:
  - Parse JSON body into `StoreConfig` fields + `table`, `schema`, `no_drop_table` flag
  - Use `_get_store(config)` to obtain a connected store instance
  - If collection exists AND `no_drop_table=false` (default): call `delete_collection()` then `create_collection()`
  - If collection exists AND `no_drop_table=true`: only call `prepare_embedding_table()`
  - If collection does NOT exist: call `create_collection()` then `prepare_embedding_table()`
  - Return `{"status": "created", "table": "...", "schema": "...", "vector_store": "..."}`
- Handle validation errors (missing table, invalid store type) with 400 responses
- Handle store errors with 500 responses
- Write unit tests with mocked store

**NOT in scope**: PUT (TASK-611), PATCH (TASK-610), helpers, route registration

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/handlers/stores/handler.py` | MODIFY | Replace `post()` stub with implementation |
| `packages/ai-parrot/tests/unit/test_vectorstore_post.py` | CREATE | Unit tests for POST endpoint |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Already imported in handler.py from TASK-608:
from parrot.stores import AbstractStore, supported_stores
from parrot.stores.models import StoreConfig
```

### Existing Signatures to Use
```python
# parrot/stores/models.py:42-59
@dataclass
class StoreConfig:
    vector_store: str = 'postgres'                                   # line 44
    table: Optional[str] = None                                      # line 45
    schema: str = 'public'                                           # line 46
    embedding_model: Union[str, dict] = field(default_factory=...)   # line 47
    dimension: int = 768                                             # line 53
    dsn: Optional[str] = None                                        # line 54
    distance_strategy: str = 'COSINE'                                # line 55
    metric_type: str = 'COSINE'                                      # line 56
    index_type: str = 'IVF_FLAT'                                     # line 57
    extra: Dict[str, Any] = field(default_factory=dict)              # line 59

# AbstractStore methods (called on the store instance from _get_store):
async def collection_exists(self, table, schema='public') -> bool            # postgres.py:2747
async def delete_collection(self, table, schema='public') -> None            # postgres.py:2772
async def create_collection(self, table, schema='public', dimension=768,
                             index_type="COSINE", metric_type='L2',
                             id_column=None, **kwargs) -> None               # postgres.py:2804
async def prepare_embedding_table(self, table, schema='public', conn=None,
                                   id_column='id', embedding_column='embedding',
                                   document_column='document', metadata_column='cmetadata',
                                   dimension=768, ..., **kwargs) -> bool     # postgres.py:808
```

### Does NOT Exist
- ~~`AbstractStore.from_config(config: StoreConfig)`~~ — no classmethod
- ~~`StoreConfig.to_store()`~~ — no method
- ~~`store.create_or_replace_collection()`~~ — no such convenience method; must check exists + delete + create manually

---

## Implementation Notes

### Pattern to Follow
```python
async def post(self) -> web.Response:
    """Create or prepare a vector store collection."""
    try:
        body = await self.json_body()  # or self.request.json()
        # Extract StoreConfig fields
        table = body.get('table')
        schema = body.get('schema', 'public')
        no_drop_table = body.get('no_drop_table', False)

        if not table:
            return self.json_response(
                {"error": "Missing required field: table"}, status=400
            )

        config = StoreConfig(
            vector_store=body.get('vector_store', 'postgres'),
            table=table,
            schema=schema,
            embedding_model=body.get('embedding_model', ...),
            dimension=body.get('dimension', 768),
            dsn=body.get('dsn'),
            distance_strategy=body.get('distance_strategy', 'COSINE'),
            metric_type=body.get('metric_type', 'COSINE'),
            index_type=body.get('index_type', 'IVF_FLAT'),
            extra=body.get('extra', {})
        )

        store = await self._get_store(config)

        exists = await store.collection_exists(table=table, schema=schema)
        if exists and not no_drop_table:
            await store.delete_collection(table=table, schema=schema)
            await store.create_collection(...)
        elif exists and no_drop_table:
            await store.prepare_embedding_table(...)
        else:
            await store.create_collection(...)
            await store.prepare_embedding_table(...)

        return self.json_response({
            "status": "created",
            "table": table,
            "schema": schema,
            "vector_store": config.vector_store
        })
    except Exception as err:
        self.logger.error(f"POST error: {err}", exc_info=True)
        return self.json_response({"error": str(err)}, status=500)
```

### Key Constraints
- Validate `vector_store` is in `supported_stores` — return 400 if not
- Validate `table` is required — return 400 if missing
- For BigQuery: `schema` is already mapped to `dataset` inside `_get_store`, but `collection_exists`/`create_collection`/`delete_collection` use `dataset` param, not `schema`. The handler must pass the correct param name based on store type.
- Use `self.json_response()` for all responses (inherited from BaseView)
- Read body via `await self.request.json()` — this is the standard aiohttp pattern

### References in Codebase
- `packages/ai-parrot/src/parrot/handlers/scraping/handler.py` — POST pattern
- User-provided code in brainstorm for create_collection flow

---

## Acceptance Criteria

- [ ] POST creates a new collection when it doesn't exist
- [ ] POST drops and recreates when collection exists and `no_drop_table=false`
- [ ] POST only prepares embedding table when `no_drop_table=true`
- [ ] Returns 400 for missing `table` field
- [ ] Returns 400 for unsupported `vector_store`
- [ ] Returns 500 with error detail for store operation failures
- [ ] Response format: `{"status": "created", "table": "...", "schema": "...", "vector_store": "..."}`
- [ ] All unit tests pass

---

## Test Specification

```python
# tests/unit/test_vectorstore_post.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestPostCreateCollection:
    @pytest.mark.asyncio
    async def test_create_new_collection(self):
        """Creates collection when it doesn't exist."""
        pass  # mock store, collection_exists=False, verify create+prepare called

    @pytest.mark.asyncio
    async def test_recreate_existing_collection(self):
        """Drops and recreates when no_drop_table=false."""
        pass  # mock store, collection_exists=True, verify delete+create+prepare

    @pytest.mark.asyncio
    async def test_prepare_only_no_drop(self):
        """Only prepares embedding table when no_drop_table=true."""
        pass  # verify only prepare_embedding_table called

    @pytest.mark.asyncio
    async def test_missing_table_returns_400(self):
        """Returns 400 when table field is missing."""
        pass

    @pytest.mark.asyncio
    async def test_unsupported_store_returns_400(self):
        """Returns 400 for unknown vector_store type."""
        pass

    @pytest.mark.asyncio
    async def test_store_error_returns_500(self):
        """Returns 500 when store operation raises."""
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
7. **Move this file** to `tasks/completed/TASK-609-post-create-collection.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (claude-sonnet)
**Date**: 2026-04-07
**Notes**: POST method already implemented in TASK-608. Created 6 unit tests covering all acceptance criteria. All pass.

**Deviations from spec**: Implementation was committed as part of TASK-608 handler.py. Only test file added here.
