# TASK-863: Reranker Data Models and Abstract Base Class

**Feature**: FEAT-126 — Local Cross-Encoder Reranker for RAG Retrieval
**Spec**: `sdd/specs/local-cross-encoder-reranker.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the foundational task for the reranker subsystem. It creates the
`parrot/rerankers/` package with the Pydantic data models (`RerankedDocument`,
`RerankerConfig`) and the `AbstractReranker` ABC. All subsequent reranker tasks
depend on these definitions.

Implements spec Modules 1 (partial), 2, and 3.

---

## Scope

- Create the `parrot/rerankers/` package directory.
- Implement `parrot/rerankers/models.py` with `RerankedDocument` and `RerankerConfig`
  Pydantic v2 models.
- Implement `parrot/rerankers/abstract.py` with the `AbstractReranker` ABC.
- Create a minimal `parrot/rerankers/__init__.py` that exports `AbstractReranker`,
  `RerankedDocument`, and `RerankerConfig`. Use lazy imports for heavy submodules
  (local, llm) — those will be added in later tasks.

**NOT in scope**:
- `LocalCrossEncoderReranker` (TASK-864)
- `LLMReranker` (TASK-865)
- Bot integration (TASK-866)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/rerankers/__init__.py` | CREATE | Package root with exports |
| `packages/ai-parrot/src/parrot/rerankers/models.py` | CREATE | RerankedDocument and RerankerConfig |
| `packages/ai-parrot/src/parrot/rerankers/abstract.py` | CREATE | AbstractReranker ABC |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.

### Verified Imports

```python
from parrot.stores.models import SearchResult   # verified: packages/ai-parrot/src/parrot/stores/models.py:7
from parrot.stores.models import Document        # verified: packages/ai-parrot/src/parrot/stores/models.py:21
from pydantic import BaseModel, Field            # verified: used throughout codebase
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/stores/models.py:7
class SearchResult(BaseModel):
    id: str
    content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    score: float
    ensemble_score: float = None
    search_source: str = None
    similarity_rank: Optional[int] = None
    mmr_rank: Optional[int] = None
```

### Does NOT Exist

- ~~`parrot/rerankers/`~~ — directory does not exist; this task creates it.
- ~~`AbstractReranker`~~ — does not exist; this task creates it.
- ~~`RerankedDocument`~~ — does not exist; this task creates it.
- ~~`RerankerConfig`~~ — does not exist; this task creates it.
- ~~`SearchResult.rerank_score`~~ — DO NOT add fields to SearchResult. Reranker data lives on RerankedDocument via composition.

---

## Implementation Notes

### Pattern to Follow

Follow the `AbstractStore` pattern in `parrot/stores/abstract.py` — ABC with one
required async method plus optional lifecycle hooks:

```python
# Reference: parrot/stores/abstract.py:17
class AbstractStore(ABC):
    def __init__(self, embedding_model=None, embedding=None, **kwargs): ...
```

### Key Constraints

- Pydantic v2 — use `model_copy()`, not `.copy()`
- `RerankedDocument` wraps `SearchResult` via composition (a `document` field), NOT inheritance
- `RerankerConfig.device` defaults to `"auto"`, `precision` defaults to `"auto"`
- `RerankerConfig.model_name` defaults to `"BAAI/bge-reranker-v2-m3"`
- `AbstractReranker.rerank()` must be `async` and `abstractmethod`
- `AbstractReranker.load()` and `cleanup()` are optional lifecycle hooks (default no-op, not abstract)
- The `__init__.py` should only import lightweight modules (models, abstract) eagerly; heavy modules (local, llm) via lazy import pattern

### Data Model Definitions (from spec §2)

```python
class RerankedDocument(BaseModel):
    document: SearchResult
    rerank_score: float = Field(...)
    rerank_rank: int = Field(..., ge=0)
    original_rank: int = Field(..., ge=0)
    rerank_model: str = Field(...)
    rerank_latency_ms: Optional[float] = None

class RerankerConfig(BaseModel):
    model_name: str = "BAAI/bge-reranker-v2-m3"
    device: str = "auto"
    precision: str = "auto"
    max_length: int = 512
    batch_size: int = 32
    trust_remote_code: bool = False
    warmup: bool = True
```

### AbstractReranker Signature (from spec §2)

```python
class AbstractReranker(ABC):
    @abstractmethod
    async def rerank(
        self,
        query: str,
        documents: list[SearchResult],
        top_n: Optional[int] = None,
    ) -> list[RerankedDocument]: ...

    async def load(self) -> None: ...     # no-op default
    async def cleanup(self) -> None: ...  # no-op default
```

---

## Acceptance Criteria

- [ ] `parrot/rerankers/` package exists with `__init__.py`, `models.py`, `abstract.py`
- [ ] `from parrot.rerankers import AbstractReranker, RerankedDocument, RerankerConfig` works
- [ ] `RerankedDocument` wraps `SearchResult` via composition
- [ ] `AbstractReranker` cannot be instantiated directly (is ABC)
- [ ] `AbstractReranker` subclass must implement `rerank()` method
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/rerankers/`

---

## Test Specification

```python
# tests/unit/rerankers/test_models_and_abstract.py
import pytest
from parrot.rerankers import AbstractReranker, RerankedDocument, RerankerConfig
from parrot.stores.models import SearchResult


def test_reranked_document_wraps_search_result():
    sr = SearchResult(id="1", content="test", metadata={}, score=0.9)
    rd = RerankedDocument(
        document=sr, rerank_score=0.95, rerank_rank=0,
        original_rank=2, rerank_model="test-model"
    )
    assert rd.document.content == "test"
    assert rd.rerank_score == 0.95


def test_reranker_config_defaults():
    cfg = RerankerConfig()
    assert cfg.model_name == "BAAI/bge-reranker-v2-m3"
    assert cfg.device == "auto"
    assert cfg.precision == "auto"
    assert cfg.warmup is True


def test_abstract_reranker_is_abc():
    with pytest.raises(TypeError):
        AbstractReranker()


@pytest.mark.asyncio
async def test_abstract_reranker_subclass_must_implement_rerank():
    class IncompleteReranker(AbstractReranker):
        pass

    with pytest.raises(TypeError):
        IncompleteReranker()


@pytest.mark.asyncio
async def test_abstract_reranker_lifecycle_hooks_are_noop():
    class MinimalReranker(AbstractReranker):
        async def rerank(self, query, documents, top_n=None):
            return []

    r = MinimalReranker()
    await r.load()      # should not raise
    await r.cleanup()   # should not raise
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/local-cross-encoder-reranker.spec.md` for full context
2. **Check dependencies** — this task has no dependencies
3. **Verify the Codebase Contract** — confirm `SearchResult` still exists at `parrot/stores/models.py:7`
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** the three files per scope above
6. **Run tests**: `pytest tests/unit/rerankers/test_models_and_abstract.py -v`
7. **Move this file** to `tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
