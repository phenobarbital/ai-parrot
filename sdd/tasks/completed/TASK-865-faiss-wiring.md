# TASK-865: Wire `FaissStore.add_documents` to the augmentation hook

**Feature**: FEAT-127 — Metadata-Driven Contextual Embedding Headers
**Spec**: `sdd/specs/contextual-embedding-headers.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-861, TASK-862
**Assigned-to**: unassigned

---

## Context

Module 4 sub-task. Wires the FAISS in-memory store into the
contextual-embedding hook. `from_documents` (line 969) delegates to
`add_documents` so only one wiring point is needed.

Spec sections: §3 Module 4, §5 Acceptance Criteria item 4.

---

## Scope

- In `FaissStore.add_documents` (`parrot/stores/faiss_store.py:367`):
  - Replace `texts = [doc.page_content for doc in documents]` (line 399)
    with `texts = self._apply_contextual_augmentation(documents)`.
  - The variable `texts` is currently passed straight to
    `self._embed_.embed_documents(texts)` — that call now embeds the
    augmented text.
  - Wherever `metadatas` (`= [doc.metadata for doc in documents]`,
    line 400) or the raw chunk text is persisted into the in-memory
    structures (`collection_data['texts']` / `['metadata']` — verify
    location around lines 430-470), continue to store the RAW
    `doc.page_content`, not the augmented `texts[i]`.
- No change to `from_documents` (line 969); it delegates to `add_documents`
  at line 986.
- Add a minimal unit test that mocks `_embed_.embed_documents` and asserts
  the embedded text is augmented when the flag is on, raw when off.

**NOT in scope**:

- Postgres / Milvus / Arango wiring — separate tasks.
- FAISS index type / training behaviour (untouched).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/stores/faiss_store.py` | MODIFY | `add_documents` (line 367). |
| `packages/ai-parrot/tests/unit/stores/test_contextual_faiss.py` | CREATE | Unit test with mocked `_embed_`. |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-04-27.

### Verified Imports

```python
from parrot.stores.utils.contextual import build_contextual_text   # CREATED by TASK-861
# _apply_contextual_augmentation inherited from AbstractStore (TASK-862).
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/stores/faiss_store.py
class FaissStore(AbstractStore):
    async def add_documents(                                       # line 367
        self,
        documents: List[Document],
        collection: str = None,
        embedding_column: str = None,
        content_column: str = None,
        metadata_column: str = None,
        **kwargs,
    ) -> None: ...

    async def from_documents(                                      # line 969
        self, documents, collection=None, **kwargs,
    ):
        # Delegates to add_documents at line 986.
```

### Existing Inline Pattern to Replace

```python
# parrot/stores/faiss_store.py:399-403
texts = [doc.page_content for doc in documents]
metadatas = [doc.metadata for doc in documents]
embeddings = await self._embed_.embed_documents(texts)
```

### Does NOT Exist

- ~~`FaissStore._apply_contextual_augmentation`~~ — inherited; do not override.
- ~~A persisted FAISS field for `contextual_header`~~ — the header lives
  inside the in-memory metadata dict already kept by the FAISS collection.
  Verify the existing storage path (around lines 430-470) writes
  `metadata` as-is; the header rides along.

---

## Implementation Notes

### Diff Sketch

```python
# Before:
texts = [doc.page_content for doc in documents]
metadatas = [doc.metadata for doc in documents]
embeddings = await self._embed_.embed_documents(texts)

# After:
texts_for_embed = self._apply_contextual_augmentation(documents)
metadatas = [doc.metadata for doc in documents]    # carries contextual_header now
embeddings = await self._embed_.embed_documents(texts_for_embed)
raw_texts = [doc.page_content for doc in documents]  # use this for any text persistence below
```

Then audit the body of `add_documents` (lines 405–470 approximately) for
any reference to `texts[i]` that goes into a `collection_data` or stored
field — replace with `raw_texts[i]`. The augmented text is **only** for
the `embed_documents` call.

### References in Codebase

- `parrot/stores/postgres.py:586` — canonical wiring example (after TASK-863).

---

## Acceptance Criteria

- [ ] `FaissStore.add_documents` calls `_apply_contextual_augmentation`.
- [ ] Stored chunk text inside the in-memory FAISS collection is RAW
      `page_content`.
- [ ] `metadata` propagates `contextual_header` when flag is True.
- [ ] Off-path is byte-identical to today.
- [ ] `pytest packages/ai-parrot/tests/unit/stores/test_contextual_faiss.py -v` passes.
- [ ] `from parrot.stores.faiss_store import FaissStore` still imports cleanly.

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/stores/test_contextual_faiss.py
from unittest.mock import AsyncMock, MagicMock
import numpy as np
import pytest

from parrot.stores.models import Document
from parrot.stores.faiss_store import FaissStore


@pytest.fixture
def docs():
    return [
        Document(page_content="Hello", metadata={
            "document_meta": {"title": "T", "section": "S"},
        }),
    ]


@pytest.fixture
def store(monkeypatch):
    s = FaissStore.__new__(FaissStore)
    s.logger = MagicMock()
    s._connected = True
    s._embed_ = MagicMock()
    s._embed_.embed_documents = AsyncMock(side_effect=lambda t: np.zeros((len(t), 4), dtype=np.float32))
    s.collection_name = "c"
    s.dimension = 4
    s.distance_strategy = MagicMock()
    s.index_type = "Flat"
    s._collections = {"c": {
        "index": MagicMock(),
        "dimension": 4,
        "is_trained": True,
        "texts": [],
        "metadata": [],
    }}
    s._initialize_collection = lambda c: None
    s._create_faiss_index = lambda d: MagicMock()
    s.contextual_embedding = False
    s.contextual_template = None
    s.contextual_max_header_tokens = 100
    return s


class TestFaissContextual:
    async def test_off_path_embeds_raw_text(self, store, docs):
        await store.add_documents(docs)
        embedded = store._embed_.embed_documents.await_args.args[0]
        assert embedded == ["Hello"]
        assert "contextual_header" not in docs[0].metadata

    async def test_on_path_embeds_augmented_text(self, store, docs):
        from parrot.stores.utils.contextual import DEFAULT_TEMPLATE
        store.contextual_embedding = True
        store.contextual_template = DEFAULT_TEMPLATE
        await store.add_documents(docs)
        embedded = store._embed_.embed_documents.await_args.args[0]
        assert embedded[0].startswith("Title: T")
        assert docs[0].metadata["contextual_header"].startswith("Title: T")
```

---

## Agent Instructions

1. Read the spec (just §3 Module 4 + §5 acceptance criterion 4).
2. Verify TASK-861 and TASK-862 are completed.
3. Update status to in-progress.
4. Apply the small diff in `faiss_store.py`. Audit downstream
   `texts[i]` references and switch them to `raw_texts[i]`.
5. Run tests.
6. Move to completed; update index.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
