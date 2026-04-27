# TASK-856: Wire `_apply_contextual_augmentation` into `AbstractStore`

**Feature**: FEAT-127 — Metadata-Driven Contextual Embedding Headers
**Spec**: `sdd/specs/contextual-embedding-headers.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-855
**Assigned-to**: unassigned

---

## Context

Module 2 of the spec. Adds the three opt-in constructor kwargs to
`AbstractStore` plus a single protected helper method that concrete stores
will call from their `add_documents` / `from_documents` to swap raw
`page_content` for the metadata-augmented text — and to write the trace of
the header back into `metadata['contextual_header']`.

This task does NOT modify any concrete store. Wiring is TASK-857..860.

Spec sections: §2 Architectural Design (Component Diagram), §3 Module 2,
§5 Acceptance Criteria items 2 & 5.

---

## Scope

- Add three kwargs to `AbstractStore.__init__`:
  - `contextual_embedding: bool = False`
  - `contextual_template: ContextualTemplate = DEFAULT_TEMPLATE`
  - `contextual_max_header_tokens: int = DEFAULT_MAX_HEADER_TOKENS`
  Read them from `**kwargs` (the existing `__init__` already uses
  `**kwargs` and a kwargs.get pattern — follow that style).
- Store as `self.contextual_embedding`, `self.contextual_template`,
  `self.contextual_max_header_tokens`.
- Add a NEW protected method on `AbstractStore`:
  ```python
  def _apply_contextual_augmentation(
      self, documents: list,
  ) -> list[str]:
      """Return the list of strings to embed, mutating each document's
      metadata['contextual_header'] in place. Off-path is byte-identical
      to [d.page_content for d in documents]."""
  ```
- When `self.contextual_embedding` is False, the method MUST return
  `[d.page_content for d in documents]` and MUST NOT touch any document's
  metadata (no `contextual_header` key written).
- When True, for each document:
  - Call `build_contextual_text(doc, self.contextual_template, self.contextual_max_header_tokens)`.
  - Mutate `doc.metadata["contextual_header"] = header` (empty string is OK).
  - Append the augmented text to the result list.
- Emit ONE summary log line per call at INFO level (NOT per chunk):
  `"Contextual embedding: %d/%d docs received header (avg header len %d chars)"`.
  Do not log at DEBUG per doc — spec §7 says that's too noisy.
- Write unit tests for the off-path / on-path behaviours (spec §4
  Module 2 rows: `test_apply_contextual_augmentation_off_path_unchanged`,
  `_writes_header_metadata`, `_does_not_mutate_page_content`).

**NOT in scope**:

- Modifying any concrete store (`postgres.py`, `milvus.py`, `faiss_store.py`,
  `arango.py`). They are TASK-857..860.
- The pure-function helper itself — that is TASK-855.
- The precedence rule between `LateChunkingProcessor` and contextual headers
  — that decision lives in TASK-857 (postgres `from_documents`).
- Returning `contextual_header` in `SearchResult.metadata` — that's TASK-861.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/stores/abstract.py` | MODIFY | Add three kwargs + `_apply_contextual_augmentation`. |
| `packages/ai-parrot/tests/unit/stores/test_abstract_contextual.py` | CREATE | Unit tests for the new hook (uses a minimal concrete subclass). |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-04-27.

### Verified Imports

```python
from parrot.stores.models import Document                             # verified: parrot/stores/models.py:21
from parrot.stores.utils.contextual import (                          # CREATED by TASK-855
    build_contextual_text,
    DEFAULT_TEMPLATE,
    DEFAULT_MAX_HEADER_TOKENS,
    ContextualTemplate,
)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/stores/abstract.py
class AbstractStore(ABC):
    def __init__(                                                      # line 32
        self,
        embedding_model: Union[dict, str] = None,
        embedding: Union[dict, Callable] = None,
        **kwargs,
    ):
        self.client: Callable = None                                   # line 38
        self.vector: Callable = None                                   # line 39
        self._embed_: Callable = None                                  # line 40
        self._connected: bool = False                                  # line 41
        # ... (uses kwargs.get('use_database', True), etc.)            # line 54
        self.logger = logging.getLogger(f"Store.{__name__}")           # line 77

    @abstractmethod
    async def from_documents(...) -> Callable: ...                     # line 175

    @abstractmethod
    async def add_documents(...) -> None: ...                          # line 207
```

### Pattern in Existing `__init__` (follow this style)

```python
self._use_database: bool = kwargs.get('use_database', True)            # line 54
self.collection_name: str = kwargs.get('collection_name', 'my_collection')  # line 56
self.dimension: int = kwargs.get("dimension", 768)                     # line 57
```

Use the same `kwargs.get(...)` pattern for the three new flags rather than
adding explicit parameters to the signature — this preserves backwards
compatibility with every existing subclass.

### Does NOT Exist

- ~~`AbstractStore.contextual_embedding`~~ — created by this task.
- ~~`AbstractStore.contextual_template`~~ — created by this task.
- ~~`AbstractStore._apply_contextual_augmentation`~~ — created by this task.
- ~~A base-class `add_documents` / `from_documents` implementation~~ — both
  remain `@abstractmethod`. This task does NOT make them concrete; it only
  adds a helper that concrete subclasses opt into.

---

## Implementation Notes

### Constructor Wiring

```python
# inside AbstractStore.__init__, after the existing kwargs.get(...) block
self.contextual_embedding: bool = kwargs.get("contextual_embedding", False)
self.contextual_template: ContextualTemplate = kwargs.get(
    "contextual_template", DEFAULT_TEMPLATE,
)
self.contextual_max_header_tokens: int = kwargs.get(
    "contextual_max_header_tokens", DEFAULT_MAX_HEADER_TOKENS,
)
```

### The Helper

```python
def _apply_contextual_augmentation(self, documents: list) -> list[str]:
    """Build the list of strings to embed, mutating contextual_header in place.

    Off-path (flag False) is byte-identical to the previous behaviour:
    return [d.page_content for d in documents] with NO metadata mutation.
    """
    if not self.contextual_embedding:
        return [d.page_content for d in documents]

    texts: list[str] = []
    headered = 0
    total_header_chars = 0
    for doc in documents:
        text, header = build_contextual_text(
            doc,
            self.contextual_template,
            self.contextual_max_header_tokens,
        )
        if doc.metadata is None:
            doc.metadata = {}
        doc.metadata["contextual_header"] = header
        if header:
            headered += 1
            total_header_chars += len(header)
        texts.append(text)

    if documents:
        avg = total_header_chars // max(headered, 1)
        self.logger.info(
            "Contextual embedding: %d/%d docs received header "
            "(avg header len %d chars)",
            headered, len(documents), avg,
        )
    return texts
```

### Key Constraints

- The helper is **synchronous** — no I/O, just dict mutation and string
  building. Pure pre-embedding step.
- Do NOT mutate `doc.page_content`. Verified by test
  `test_apply_contextual_augmentation_does_not_mutate_page_content`.
- Off-path MUST be byte-identical to the existing list-comprehension
  pattern used by every store today (see `parrot/stores/postgres.py:621`).

### References in Codebase

- `parrot/stores/abstract.py` — existing class (extend it).
- `parrot/stores/postgres.py:621` — current call site
  `texts = [doc.page_content for doc in documents]` that store wirings
  (TASK-857..860) will replace with `self._apply_contextual_augmentation(documents)`.

---

## Acceptance Criteria

- [ ] `AbstractStore.__init__` accepts `contextual_embedding`,
      `contextual_template`, `contextual_max_header_tokens` via `**kwargs`.
- [ ] All three default to off / sensible values.
- [ ] `_apply_contextual_augmentation` exists, is synchronous, returns
      `list[str]`, mutates `metadata['contextual_header']` ONLY when the
      flag is True.
- [ ] Off-path test: with flag False, returned list equals
      `[d.page_content for d in docs]` exactly, AND no document has
      `contextual_header` in its metadata.
- [ ] On-path test: with flag True, every input document has
      `metadata['contextual_header']` set (string, possibly empty).
- [ ] `Document.page_content` is byte-equal before and after the call,
      asserted in a dedicated test.
- [ ] Single summary log line per call (not per chunk).
- [ ] All Module 2 unit tests in spec §4 pass:
      `pytest packages/ai-parrot/tests/unit/stores/test_abstract_contextual.py -v`
- [ ] No subclass breaks. Smoke-import every concrete store:
      `python -c "from parrot.stores import postgres, milvus, faiss_store, arango"`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/stores/test_abstract_contextual.py
import pytest
from parrot.stores.abstract import AbstractStore
from parrot.stores.models import Document


class _DummyStore(AbstractStore):
    """Minimal concrete store for testing the augmentation helper only."""
    async def connection(self): return (None, None)
    async def disconnect(self): pass
    def get_vector(self, metric_type=None, **kwargs): return None
    async def similarity_search(self, query, **kwargs): return []
    async def from_documents(self, documents, collection=None, **kwargs): return self
    async def create_collection(self, collection): pass
    async def add_documents(self, documents, collection=None, **kwargs): pass


@pytest.fixture
def docs():
    return [
        Document(page_content="A", metadata={"document_meta": {"title": "T1"}}),
        Document(page_content="B", metadata={"document_meta": {}}),
        Document(page_content="C", metadata={}),
    ]


class TestApplyContextualAugmentation:
    def test_off_path_unchanged(self, docs):
        store = _DummyStore(contextual_embedding=False, use_database=False)
        out = store._apply_contextual_augmentation(docs)
        assert out == ["A", "B", "C"]
        for d in docs:
            assert "contextual_header" not in d.metadata

    def test_on_path_writes_header_metadata(self, docs):
        store = _DummyStore(contextual_embedding=True, use_database=False)
        store._apply_contextual_augmentation(docs)
        for d in docs:
            assert "contextual_header" in d.metadata

    def test_on_path_does_not_mutate_page_content(self, docs):
        before = [d.page_content for d in docs]
        store = _DummyStore(contextual_embedding=True, use_database=False)
        store._apply_contextual_augmentation(docs)
        after = [d.page_content for d in docs]
        assert before == after

    def test_constructor_defaults(self):
        store = _DummyStore(use_database=False)
        assert store.contextual_embedding is False
        assert store.contextual_max_header_tokens == 100
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** for context on the helper contract.
2. **Verify TASK-855 is in `sdd/tasks/completed/`**. If not, stop and unblock that first.
3. **Verify the Codebase Contract** — re-read `abstract.py:32-90` to confirm the
   `kwargs.get(...)` pattern is still in use.
4. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`.
5. **Implement** in two edits: constructor block + new method.
6. **Run tests** — all unit tests pass + smoke-import every concrete store.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
