# TASK-860: Wire `ArangoStore.add_document` to the augmentation hook

**Feature**: FEAT-127 — Metadata-Driven Contextual Embedding Headers
**Spec**: `sdd/specs/contextual-embedding-headers.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-855, TASK-856
**Assigned-to**: unassigned

---

## Context

Module 4 sub-task. Arango is unusual in this codebase: its `add_documents`
(line 539) is a batch loop that calls `add_document` (line 465) per row,
and `add_document` is the call site that actually invokes
`_generate_embedding(text)`. The augmentation must therefore happen
INSIDE `add_document` (or be applied by `add_documents` before delegating)
so that the embedding sees the augmented text but the persisted
`text_column` remains the raw chunk.

`from_documents` (line 870) delegates to `add_documents` (line 893) — no
extra wiring there.

Spec sections: §3 Module 4, §5 Acceptance Criteria item 4.

---

## Scope

- The cleanest fit is to apply augmentation in `add_documents` (the batch
  entry point at line 539) so the existing single-doc `add_document` is
  not perturbed for callers who pass plain dicts:
  - At the top of `add_documents`, when `self.contextual_embedding` is
    True AND the input is a list of `Document` objects (not dicts), call
    `self._apply_contextual_augmentation(documents)` to produce a parallel
    `texts_for_embed` list and write `contextual_header` into each doc's
    metadata.
  - Convert each `Document` into a dict via `_document_to_dict(doc)` (line
    492) but with `text_column` set to RAW `doc.page_content`, then add
    `embedding_column` directly using
    `await self._generate_embedding(texts_for_embed[i])` (computed from
    the augmented text). The presence of `embedding_column` in the dict
    short-circuits the auto-embed branch in `add_document` (line 497).
  - When `self.contextual_embedding` is False, behaviour is unchanged
    (current per-doc auto-embed flow inside `add_document`).
- Documents passed as raw dicts (no `Document` wrapper) are out of scope
  for v1 — the helper requires a `Document` to read `document_meta` from.
  Document this in the completion note.
- `from_documents` requires no change.
- Add a minimal unit test that mocks `_generate_embedding` and asserts
  the embedded text is augmented when the flag is on, raw when off.

**NOT in scope**:

- Postgres / Milvus / Faiss wiring — separate tasks.
- Augmentation for the dict-input path (callers that already build their
  own dicts and don't go through `Document`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/stores/arango.py` | MODIFY | `add_documents` (line 539). |
| `packages/ai-parrot/tests/unit/stores/test_contextual_arango.py` | CREATE | Unit test with mocked `_generate_embedding` and `_db.insert_document`. |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-04-27.

### Verified Imports

```python
from parrot.stores.models import Document                          # parrot/stores/models.py:21
# _apply_contextual_augmentation inherited from AbstractStore (TASK-856).
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/stores/arango.py
class ArangoStore(AbstractStore):
    async def add_document(                                         # line 465
        self,
        document: Union[Document, dict],
        collection: str = None,
        upsert: bool = True,
        upsert_key: Optional[str] = None,
        upsert_metadata_keys: Optional[List[str]] = None,
        **kwargs,
    ) -> Dict[str, Any]: ...

    async def add_documents(                                        # line 539
        self,
        documents: List[Union[Document, dict]],
        collection: str = None,
        upsert: bool = True,
        batch_size: int = 100,
        **kwargs,
    ) -> int: ...

    async def from_documents(                                       # line 870
        self, documents, collection=None, **kwargs,
    ):
        # Delegates to add_documents at line 893.
```

### Existing Inline Patterns

```python
# parrot/stores/arango.py:491-500   (inside add_document)
if isinstance(document, Document):
    doc_dict = self._document_to_dict(document)
else:
    doc_dict = document.copy()

# Generate embedding if needed
if self.embedding_column not in doc_dict and self.text_column in doc_dict:
    text = doc_dict[self.text_column]
    embedding = await self._generate_embedding(text)
    doc_dict[self.embedding_column] = embedding
```

`self.embedding_column`, `self.text_column`, `self._generate_embedding`,
`self._document_to_dict` all exist and are called as shown.

### Does NOT Exist

- ~~`ArangoStore._apply_contextual_augmentation`~~ — inherited; do not override.
- ~~An augmented variant of `add_document`~~ — keep `add_document` untouched.
  The augmentation is plumbed in `add_documents` only.

---

## Implementation Notes

### Diff Sketch (in `add_documents`, line 539)

```python
async def add_documents(self, documents, collection=None, upsert=True, batch_size=100, **kwargs) -> int:
    collection = collection or self.collection_name
    count = 0

    # ── Optional contextual augmentation for Document inputs ──
    docs_only = [d for d in documents if isinstance(d, Document)]
    augmented_texts: dict[int, str] = {}
    if self.contextual_embedding and docs_only:
        # Compute augmented text per Document; mutates contextual_header in place.
        per_doc_texts = self._apply_contextual_augmentation(docs_only)
        # Build a map from document identity → augmented text.
        for doc, atext in zip(docs_only, per_doc_texts):
            augmented_texts[id(doc)] = atext

    for i in range(0, len(documents), batch_size):
        batch = documents[i:i + batch_size]
        for doc in batch:
            try:
                if isinstance(doc, Document) and id(doc) in augmented_texts:
                    # Pre-embed using augmented text; pass the dict to add_document
                    # with embedding pre-populated to short-circuit auto-embed.
                    doc_dict = self._document_to_dict(doc)
                    doc_dict[self.embedding_column] = await self._generate_embedding(
                        augmented_texts[id(doc)]
                    )
                    await self.add_document(
                        doc_dict, collection=collection, upsert=upsert, **kwargs,
                    )
                else:
                    await self.add_document(
                        doc, collection=collection, upsert=upsert, **kwargs,
                    )
                count += 1
            except Exception as e:
                self.logger.error(f"Error adding document in batch: {e}")

    self.logger.info(f"Added {count} documents to {collection}")
    return count
```

### Off-Path Invariant

When `self.contextual_embedding` is False, `add_documents` behaves
exactly as today — the early-augment block is skipped, and
`add_document` receives `Document` objects directly as before.

### References in Codebase

- `parrot/stores/postgres.py:586` — canonical wiring example (after TASK-857).

---

## Acceptance Criteria

- [ ] `ArangoStore.add_documents` calls `_apply_contextual_augmentation`
      for Document inputs when the flag is True.
- [ ] Persisted `text_column` carries RAW `page_content` (verify via
      `_document_to_dict` round-trip).
- [ ] `metadata` (and therefore the persisted dict) carries
      `contextual_header` when the flag is True.
- [ ] Dict inputs are unchanged (early-augment block skips them).
- [ ] Off-path is byte-identical to today.
- [ ] `pytest packages/ai-parrot/tests/unit/stores/test_contextual_arango.py -v` passes.
- [ ] `from parrot.stores.arango import ArangoStore` still imports cleanly.

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/stores/test_contextual_arango.py
from unittest.mock import AsyncMock, MagicMock
import pytest

from parrot.stores.models import Document
from parrot.stores.arango import ArangoStore


@pytest.fixture
def store():
    s = ArangoStore.__new__(ArangoStore)
    s.logger = MagicMock()
    s.collection_name = "c"
    s.embedding_column = "embedding"
    s.text_column = "text"
    s._db = MagicMock()
    s._db.insert_document = AsyncMock(return_value={"_key": "k"})
    s._db.update_document = AsyncMock(return_value={"_key": "k"})
    s._generate_embedding = AsyncMock(side_effect=lambda t: [0.0] * 4)
    s._find_existing_document = AsyncMock(return_value=None)
    s._document_to_dict = lambda d: {
        s.text_column: d.page_content,
        "metadata": d.metadata,
    }
    s.contextual_embedding = False
    s.contextual_template = None
    s.contextual_max_header_tokens = 100
    return s


@pytest.fixture
def docs():
    return [Document(page_content="Hello", metadata={
        "document_meta": {"title": "T"},
    })]


class TestArangoContextual:
    async def test_off_path_embeds_raw(self, store, docs):
        await store.add_documents(docs)
        embedded_text = store._generate_embedding.await_args.args[0]
        assert embedded_text == "Hello"
        assert "contextual_header" not in docs[0].metadata

    async def test_on_path_embeds_augmented(self, store, docs):
        from parrot.stores.utils.contextual import DEFAULT_TEMPLATE
        store.contextual_embedding = True
        store.contextual_template = DEFAULT_TEMPLATE
        await store.add_documents(docs)
        embedded_text = store._generate_embedding.await_args.args[0]
        assert embedded_text.startswith("Title: T")
        assert docs[0].metadata["contextual_header"].startswith("Title: T")
```

---

## Agent Instructions

1. Read the spec (just §3 Module 4 + §5 acceptance criterion 4).
2. Verify TASK-855 and TASK-856 are completed.
3. Update status to in-progress.
4. Apply the diff in `arango.py` `add_documents` only.
5. Run tests.
6. Move to completed; update index.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
