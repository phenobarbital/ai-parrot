# TASK-607: VectorStoreHelper (Metadata Endpoints)

**Feature**: vectorstore-handler-api
**Spec**: `sdd/specs/vectorstore-handler-api.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-606
**Assigned-to**: unassigned

---

## Context

> Implements Spec Module 2. Creates the `VectorStoreHelper(BaseHandler)` class that
> serves unauthenticated GET endpoints for metadata: supported stores, embeddings,
> loaders, and index types. These are public endpoints used by frontends to populate
> configuration dropdowns.

---

## Scope

- Create `parrot/handlers/stores/helpers.py` with `VectorStoreHelper(BaseHandler)`
- Implement static methods:
  - `supported_stores()` → returns `supported_stores` dict
  - `supported_embeddings()` → returns `supported_embeddings` dict
  - `supported_loaders()` → returns cleaned `LOADER_MAPPING` (extension → class name, not tuples)
  - `supported_index_types()` → returns list from `DistanceStrategy` enum values
- Write unit tests for each helper method

**NOT in scope**: route registration (TASK-612), authentication, handler implementation

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/handlers/stores/helpers.py` | CREATE | VectorStoreHelper class |
| `packages/ai-parrot/tests/unit/test_vectorstore_helper.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from navigator.views import BaseHandler                          # navigator.views (installed package)
from parrot.stores import supported_stores                       # parrot/stores/__init__.py:3
from parrot.stores.models import DistanceStrategy                # parrot/stores/models.py:30
from parrot.embeddings import supported_embeddings               # parrot/embeddings/__init__.py:3
from parrot_loaders.factory import LOADER_MAPPING                # parrot_loaders/factory.py:12
```

### Existing Signatures to Use
```python
# parrot/stores/__init__.py:3-10
supported_stores = {
    'postgres': 'PgVectorStore',
    'milvus': 'MilvusStore',
    'kb': 'KnowledgeBaseStore',
    'faiss_store': 'FaissStore',
    'arango': 'ArangoStore',
    'bigquery': 'BigQueryStore',
}

# parrot/embeddings/__init__.py:3-7
supported_embeddings = {
    'huggingface': 'SentenceTransformerModel',
    'google': 'GoogleEmbeddingModel',
    'openai': 'OpenAIEmbeddingModel',
}

# parrot/stores/models.py:30-38
class DistanceStrategy(str, Enum):
    EUCLIDEAN_DISTANCE = "EUCLIDEAN_DISTANCE"                    # line 34
    MAX_INNER_PRODUCT = "MAX_INNER_PRODUCT"                      # line 35
    DOT_PRODUCT = "DOT_PRODUCT"                                  # line 36
    JACCARD = "JACCARD"                                          # line 37
    COSINE = "COSINE"                                            # line 38

# parrot_loaders/factory.py:12-48 — LOADER_MAPPING
# Maps extensions to (module_name, class_name) tuples, e.g.:
# '.pdf': ('pdf', 'PDFLoader'),
# '.txt': ('txt', 'TextLoader'),
# etc.

# parrot/handlers/google_generation.py:23-58 — Pattern reference
class GoogleGenerationHelper(BaseHandler):
    @staticmethod
    def list_models() -> list[str]:
        return [model.value for model in GoogleModel]
```

### Does NOT Exist
- ~~`parrot.stores.list_stores()`~~ — no function; use `supported_stores` dict directly
- ~~`parrot.embeddings.list_embeddings()`~~ — no function; use `supported_embeddings` dict directly
- ~~`parrot_loaders.factory.list_loaders()`~~ — no function; use `LOADER_MAPPING` dict directly
- ~~`BaseHandler.json_response()`~~ — BaseHandler does NOT have `json_response`; it's a utility class, not an HTTP handler. Only BaseView has `json_response`.

---

## Implementation Notes

### Pattern to Follow
```python
# Follow GoogleGenerationHelper pattern from parrot/handlers/google_generation.py
class VectorStoreHelper(BaseHandler):
    """Public metadata endpoints for vector store configuration."""

    @staticmethod
    def supported_stores() -> dict:
        return supported_stores

    @staticmethod
    def supported_embeddings() -> dict:
        return supported_embeddings

    @staticmethod
    def supported_loaders() -> dict:
        # Clean LOADER_MAPPING: return {ext: class_name} instead of {ext: (module, class)}
        return {ext: cls_name for ext, (_, cls_name) in LOADER_MAPPING.items()}

    @staticmethod
    def supported_index_types() -> list:
        return [strategy.value for strategy in DistanceStrategy]
```

### Key Constraints
- All methods are `@staticmethod` — no instance state needed
- `supported_loaders()` must transform the LOADER_MAPPING tuples into a clean `{ext: class_name}` dict
- This is a helper class, NOT an HTTP handler — it has no `get()`/`post()` methods
- The actual HTTP routing to these methods happens in VectorStoreHandler.get() (TASK-608/612)

### References in Codebase
- `packages/ai-parrot/src/parrot/handlers/google_generation.py` — GoogleGenerationHelper pattern
- `packages/ai-parrot/src/parrot/handlers/scheduler.py` — SchedulerCatalogHelper pattern

---

## Acceptance Criteria

- [ ] `from parrot.handlers.stores.helpers import VectorStoreHelper` works
- [ ] `VectorStoreHelper.supported_stores()` returns the `supported_stores` dict
- [ ] `VectorStoreHelper.supported_embeddings()` returns the `supported_embeddings` dict
- [ ] `VectorStoreHelper.supported_loaders()` returns `{ext: class_name}` format
- [ ] `VectorStoreHelper.supported_index_types()` returns list of DistanceStrategy values
- [ ] All unit tests pass

---

## Test Specification

```python
# tests/unit/test_vectorstore_helper.py
from parrot.handlers.stores.helpers import VectorStoreHelper


class TestVectorStoreHelper:
    def test_supported_stores(self):
        """Returns dict of supported stores."""
        result = VectorStoreHelper.supported_stores()
        assert isinstance(result, dict)
        assert 'postgres' in result
        assert result['postgres'] == 'PgVectorStore'

    def test_supported_embeddings(self):
        """Returns dict of supported embeddings."""
        result = VectorStoreHelper.supported_embeddings()
        assert isinstance(result, dict)
        assert 'huggingface' in result

    def test_supported_loaders(self):
        """Returns clean ext→class_name mapping."""
        result = VectorStoreHelper.supported_loaders()
        assert isinstance(result, dict)
        assert '.pdf' in result
        assert result['.pdf'] == 'PDFLoader'
        # Must be string values, NOT tuples
        for ext, cls_name in result.items():
            assert isinstance(cls_name, str), f"{ext} value should be str, got {type(cls_name)}"

    def test_supported_index_types(self):
        """Returns list of DistanceStrategy values."""
        result = VectorStoreHelper.supported_index_types()
        assert isinstance(result, list)
        assert 'COSINE' in result
        assert 'EUCLIDEAN_DISTANCE' in result
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-606 is in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-607-vectorstore-helper.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (claude-sonnet)
**Date**: 2026-04-07
**Notes**: Created VectorStoreHelper(BaseHandler) with 4 static methods. All 6 unit tests pass.

**Deviations from spec**: none
