# TASK-864: Wire `MilvusStore.add_documents` to the augmentation hook

**Feature**: FEAT-127 — Metadata-Driven Contextual Embedding Headers
**Spec**: `sdd/specs/contextual-embedding-headers.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-861, TASK-862
**Assigned-to**: unassigned

---

## Context

Module 4 sub-task. Wires Milvus into the contextual-embedding hook. Same
pattern as TASK-863 but the diff is much smaller because Milvus has only
`add_documents`; `from_documents` delegates to `add_documents`.

Spec sections: §3 Module 4, §5 Acceptance Criteria item 4.

---

## Scope

- In `MilvusStore.add_documents` (`parrot/stores/milvus.py:427`):
  - Replace `texts = [doc.page_content for doc in documents]` (line 446)
    with `texts = self._apply_contextual_augmentation(documents)`.
  - Keep `self._document_column` and `self._text_column` set from
    `doc.page_content` — i.e. read RAW content for those columns, NOT
    the augmented text. Adjust the row-build loop accordingly.
  - `metadatas[i]` now carries `contextual_header` after the hook runs;
    pass through into `self._metadata_column` unchanged.
- No change to `from_documents`; it delegates to `add_documents` (line 493).
- Add a minimal unit test mirroring the postgres tests in TASK-863 but
  asserting against the Milvus row-build instead of SQL values.

**NOT in scope**:

- Postgres / Faiss / Arango wiring — separate tasks.
- Any change to embedding clients or the `pymilvus` integration.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/stores/milvus.py` | MODIFY | `add_documents` (line 427). |
| `packages/ai-parrot/tests/unit/stores/test_contextual_milvus.py` | CREATE | Unit test with mocked `_connection.insert`. |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-04-27.

### Verified Imports

```python
from parrot.stores.utils.contextual import build_contextual_text   # CREATED by TASK-861
# _apply_contextual_augmentation is inherited from AbstractStore (TASK-862).
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/stores/milvus.py
class MilvusStore(AbstractStore):
    async def add_documents(                                       # line 427
        self,
        documents: List[Document],
        collection: str = None,
        **kwargs,
    ) -> None: ...

    async def from_documents(                                      # line 475
        self,
        documents: List[Any],
        collection: str = None,
        **kwargs,
    ) -> "MilvusStore":
        # Delegates to add_documents at line 493 — no separate wiring needed.
```

### Existing Inline Pattern to Replace

```python
# parrot/stores/milvus.py:446-461
texts = [doc.page_content for doc in documents]
embeddings = await self._embed_.embed_documents(texts)
metadatas = [doc.metadata for doc in documents]

rows: List[Dict[str, Any]] = []
for i, doc in enumerate(documents):
    emb = embeddings[i]
    if isinstance(emb, np.ndarray):
        emb = emb.tolist()
    rows.append({
        self._id_column: str(uuid.uuid4()),
        self._embedding_column: emb,
        self._document_column: doc.page_content,
        self._text_column: doc.page_content,
        self._metadata_column: metadatas[i] or {},
    })
```

### Does NOT Exist

- ~~`MilvusStore._apply_contextual_augmentation`~~ — inherited; do not override.
- ~~A `contextual_header` column on Milvus collections~~ — no schema change;
  the header travels inside `self._metadata_column` (JSON-typed).

---

## Implementation Notes

### Diff Sketch

```python
# Before (lines 446-461):
texts = [doc.page_content for doc in documents]
embeddings = await self._embed_.embed_documents(texts)
metadatas = [doc.metadata for doc in documents]
rows = [...]
    self._document_column: doc.page_content,
    self._text_column: doc.page_content,

# After:
texts_for_embed = self._apply_contextual_augmentation(documents)
embeddings = await self._embed_.embed_documents(texts_for_embed)
metadatas = [doc.metadata for doc in documents]   # now contains contextual_header
rows = [...]
    self._document_column: doc.page_content,        # raw content, not augmented
    self._text_column: doc.page_content,            # raw content, not augmented
    self._metadata_column: metadatas[i] or {},      # passes through contextual_header
```

### Off-Path Invariant

When `self.contextual_embedding` is False, the row dicts MUST be byte-identical
to today (modulo the UUID). Test by comparing the row passed to
`self._connection.insert` against a baseline.

### References in Codebase

- `parrot/stores/postgres.py:586` — same pattern, the canonical example
  (after TASK-863 is implemented).

---

## Acceptance Criteria

- [ ] `MilvusStore.add_documents` calls `_apply_contextual_augmentation`.
- [ ] `_document_column` and `_text_column` store RAW `page_content`.
- [ ] `_metadata_column` propagates `contextual_header` when flag is True.
- [ ] Off-path is byte-identical to today (regression test passes).
- [ ] `pytest packages/ai-parrot/tests/unit/stores/test_contextual_milvus.py -v` passes.
- [ ] `from parrot.stores.milvus import MilvusStore` still imports cleanly.

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/stores/test_contextual_milvus.py
from unittest.mock import AsyncMock, MagicMock
import numpy as np
import pytest

from parrot.stores.models import Document
from parrot.stores.milvus import MilvusStore


@pytest.fixture
def docs():
    return [
        Document(
            page_content="Body A",
            metadata={"document_meta": {"title": "Doc A", "section": "S"}},
        ),
        Document(page_content="Body B", metadata={}),
    ]


@pytest.fixture
def store():
    s = MilvusStore.__new__(MilvusStore)
    s.logger = MagicMock()
    s._connected = True
    s._connection = MagicMock()
    s._connection.insert = MagicMock()
    s._embed_ = MagicMock()
    s._embed_.embed_documents = AsyncMock(side_effect=lambda t: np.zeros((len(t), 4)))
    s.collection_name = "c"
    s._id_column = "id"
    s._embedding_column = "emb"
    s._document_column = "doc"
    s._text_column = "text"
    s._metadata_column = "meta"
    s.contextual_embedding = False
    s.contextual_template = None
    s.contextual_max_header_tokens = 100
    return s


class TestMilvusContextual:
    async def test_off_path_uses_raw_text(self, store, docs):
        await store.add_documents(docs)
        embedded = store._embed_.embed_documents.await_args.args[0]
        assert embedded == ["Body A", "Body B"]
        rows = store._connection.insert.call_args.kwargs["data"]
        assert rows[0]["doc"] == "Body A"

    async def test_on_path_embeds_header(self, store, docs):
        from parrot.stores.utils.contextual import DEFAULT_TEMPLATE
        store.contextual_embedding = True
        store.contextual_template = DEFAULT_TEMPLATE
        await store.add_documents(docs)
        embedded = store._embed_.embed_documents.await_args.args[0]
        assert embedded[0].startswith("Title: Doc A")
        rows = store._connection.insert.call_args.kwargs["data"]
        # Document column stores RAW content, not augmented.
        assert rows[0]["doc"] == "Body A"
        # Metadata carries the header.
        assert rows[0]["meta"]["contextual_header"].startswith("Title: Doc A")
```

---

## Agent Instructions

1. Read the spec (just §3 Module 4 + §5 acceptance criterion 4).
2. Verify TASK-861 and TASK-862 are completed.
3. Update status to in-progress.
4. Apply the small diff in `milvus.py`.
5. Run tests; fix until green.
6. Move to completed; update index.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
