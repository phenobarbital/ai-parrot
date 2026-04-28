# TASK-863: Wire `PgVectorStore` add_documents / from_documents to the augmentation hook

**Feature**: FEAT-127 — Metadata-Driven Contextual Embedding Headers
**Spec**: `sdd/specs/contextual-embedding-headers.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-861, TASK-862
**Assigned-to**: unassigned

---

## Context

Module 3 of the spec. Postgres is the mainstream store and the only
non-negotiable wiring for v1 (per spec §8 open question 4). This task
replaces the inline `texts = [doc.page_content for doc in documents]`
pattern in `add_documents` and the `LateChunkingProcessor`-driven path in
`from_documents` with the new `_apply_contextual_augmentation` hook from
TASK-862 — and persists `contextual_header` into the metadata column atomically
with the row.

It also enforces the precedence rule (decided by author in spec §8 open
question 3): when both `store_full_document=True` (late chunking) and
`contextual_embedding=True` are configured, **metadata-header wins** —
the metadata-derived header is applied on top of the chunk text, and the
late-chunking neighbour-context is NOT additionally prepended for chunks.

Spec sections: §3 Module 3, §5 Acceptance Criteria items 3 & 6, §7 Risk #6,
§8 Open Question 3.

---

## Scope

- In `PgVectorStore.add_documents` (`parrot/stores/postgres.py:586`):
  - Replace `texts = [doc.page_content for doc in documents]` with
    `texts = self._apply_contextual_augmentation(documents)`.
  - Keep the existing `embeddings = await self._embed_.embed_documents(texts)`
    call unchanged.
  - Keep `content_column: texts[i].replace("\x00", "")` storing the RAW
    chunk content (i.e. read from `documents[i].page_content`, not from
    the augmented `texts[i]`). The augmentation is for embedding only —
    `page_content` must remain the user-facing chunk.
  - Ensure `metadatas[i]` (which is `documents[i].metadata`) carries the
    `contextual_header` key written by the hook before sanitising/inserting.
- In `PgVectorStore.from_documents` (`parrot/stores/postgres.py:2551`):
  - When `self.contextual_embedding` is True:
    - For each chunk produced by `LateChunkingProcessor`, build a
      `Document` view (`page_content=chunk_info.chunk_text`,
      `metadata=chunk_info.metadata` — which inherits the parent doc's
      `document_meta`), pass it through `_apply_contextual_augmentation`,
      and re-embed using `self._embed_.embed_documents([augmented_text])`
      INSTEAD OF using the late-chunking-produced `chunk_info.chunk_embedding`.
    - This is the precedence rule: metadata-header wins; late-chunking's
      neighbour-context embedding is discarded for affected chunks.
    - Write `contextual_header` into the chunk's `metadata` before insert.
  - When False, behaviour is byte-identical to today.
  - Apply the same hook to the `store_full_document` path: the parent
    document's full embedding uses the augmented text; `content_column`
    stores raw `document.page_content`.
- Verify with the Module-3 integration tests in spec §4
  (`test_pgvector_add_documents_contextual_off_baseline`,
  `_on_uses_header`, `test_pgvector_from_documents_contextual_on`).

**NOT in scope**:

- Other stores (Milvus, Faiss, Arango) — TASK-864..860.
- Returning `contextual_header` in `SearchResult.metadata` — TASK-861.
- Migration tooling for existing collections — TASK-862.
- Documentation page — TASK-863.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/stores/postgres.py` | MODIFY | `add_documents` (line 586), `from_documents` (line 2551). |
| `packages/ai-parrot/tests/integration/stores/test_contextual_pgvector.py` | CREATE | Integration tests with a mocked `_embed_`. |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-04-27.

### Verified Imports

```python
from parrot.stores.models import Document                                  # parrot/stores/models.py:21
from parrot.stores.utils.contextual import build_contextual_text           # CREATED by TASK-861
# AbstractStore._apply_contextual_augmentation is inherited — no import needed.
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/stores/postgres.py
class PgVectorStore(AbstractStore):
    async def add_documents(                                                # line 586
        self,
        documents: List[Document],
        table: str = None,
        schema: str = None,
        embedding_column: str = "embedding",
        content_column: str = "document",
        metadata_column: str = "cmetadata",
        **kwargs,
    ) -> None: ...

    async def from_documents(                                               # line 2551
        self,
        documents: List[Document],
        table: str = None,
        schema: str = None,
        embedding_column: str = "embedding",
        content_column: str = "document",
        metadata_column: str = "cmetadata",
        chunk_size: int = 8192,
        chunk_overlap: int = 200,
        store_full_document: bool = True,
        **kwargs,
    ) -> Dict[str, Any]: ...
```

### Existing Inline Patterns to Replace

```python
# parrot/stores/postgres.py:621-623   (inside add_documents)
texts = [doc.page_content for doc in documents]
embeddings = await self._embed_.embed_documents(texts)
metadatas = [doc.metadata for doc in documents]
```

```python
# parrot/stores/postgres.py:2619-2656 (inside from_documents)
for doc_idx, document in enumerate(documents):
    document_id = f"doc_{doc_idx:06d}_{uuid.uuid4().hex[:8]}"
    full_embedding, chunk_infos = await chunking_processor.process_document_late_chunking(
        document_text=document.page_content,
        document_id=document_id,
        metadata=document.metadata,
    )
    if store_full_document:
        all_inserts.append({
            self._id_column: document_id,
            embedding_column: full_embedding.tolist(),
            content_column: document.page_content,
            metadata_column: full_doc_metadata,
        })
    for chunk_info in chunk_infos:
        embed = chunk_info.chunk_embedding ...
        all_inserts.append({
            self._id_column: chunk_info.chunk_id,
            embedding_column: embed,
            content_column: chunk_info.chunk_text,
            metadata_column: chunk_info.metadata,
        })
```

### Existing PgVector Internals

```python
# parrot/stores/postgres.py
self._id_column                                                              # used at lines 648, 2640, 2651
self._text_column                                                            # used at line 640
self._sanitize_metadata(metadata: dict) -> dict                              # used at line 653
self.embedding_store                                                         # SQLAlchemy table object
self._define_collection_store(...)                                           # used at lines 632, 2602
```

### Does NOT Exist

- ~~`PgVectorStore.contextual_embedding`~~ — inherited from `AbstractStore`
  (TASK-862 added it). Just read `self.contextual_embedding`.
- ~~A `contextual_header` column~~ — no schema migration. The header lives
  inside `cmetadata` (`metadata_column`), already a JSONB blob.
- ~~`PgVectorStore._apply_contextual_augmentation`~~ — inherited; do NOT
  override.
- ~~`LateChunkingProcessor.with_contextual_header(...)` or similar~~ —
  not real. The precedence rule is implemented in `from_documents`, not in
  the chunking processor.

---

## Implementation Notes

### `add_documents` Diff Sketch

```python
# Before (parrot/stores/postgres.py:621-623):
texts = [doc.page_content for doc in documents]
embeddings = await self._embed_.embed_documents(texts)
metadatas = [doc.metadata for doc in documents]

# After:
texts_for_embed = self._apply_contextual_augmentation(documents)  # mutates metadata in place
embeddings = await self._embed_.embed_documents(texts_for_embed)
raw_texts = [doc.page_content for doc in documents]               # for content_column
metadatas = [doc.metadata for doc in documents]                   # now carries contextual_header

# Then in the values list-comp at line 646-656, replace:
#   content_column: texts[i].replace("\x00", "")
# with:
#   content_column: raw_texts[i].replace("\x00", "")
```

### `from_documents` Diff Sketch

The complication: `LateChunkingProcessor.process_document_late_chunking`
already returns chunk embeddings derived from neighbour-context text.
When `self.contextual_embedding` is True, we discard those embeddings and
re-embed using metadata-augmented text:

```python
for doc_idx, document in enumerate(documents):
    document_id = f"doc_{doc_idx:06d}_{uuid.uuid4().hex[:8]}"

    full_embedding, chunk_infos = await chunking_processor.process_document_late_chunking(
        document_text=document.page_content,
        document_id=document_id,
        metadata=document.metadata,
    )

    # ── Precedence: metadata-header wins over late-chunking when both on ──
    if self.contextual_embedding:
        # Re-embed full document with contextual header
        parent_view = Document(
            page_content=document.page_content,
            metadata=dict(document.metadata or {}),
        )
        [parent_text] = self._apply_contextual_augmentation([parent_view])
        [full_embedding] = await self._embed_.embed_documents([parent_text])
        full_header = parent_view.metadata.get("contextual_header", "")

        # Re-embed each chunk with contextual header (chunk_info.metadata
        # already carries document_meta inherited from parent).
        chunk_views = [
            Document(
                page_content=ci.chunk_text,
                metadata=dict(ci.metadata or {}),
            )
            for ci in chunk_infos
        ]
        chunk_texts = self._apply_contextual_augmentation(chunk_views)
        chunk_embeds = await self._embed_.embed_documents(chunk_texts)
        for ci, view, emb in zip(chunk_infos, chunk_views, chunk_embeds):
            ci.chunk_embedding = emb
            ci.metadata = view.metadata  # carries contextual_header now

    # ... existing all_inserts.append(...) blocks unchanged.
    # full document branch should set full_doc_metadata['contextual_header']
    # = full_header when augmentation was applied.
```

### Logging

The base helper already emits one summary log per `_apply_contextual_augmentation`
call. In `from_documents` the helper is called twice per source document
(parent + chunks), so for a batch of 50 docs you'll get 101 log lines —
acceptable. If this is too noisy in practice, hoist the augmentation into
a single batched call (parent + all chunks together) — note this in the
completion note as a follow-up if you take that route.

### Critical Invariant — Tests Must Cover

`PgVectorStore.add_documents(documents, contextual_embedding=False)` —
the off-path — MUST produce byte-identical SQL `values` to today. Write a
regression test that captures the values list (mock the SQLAlchemy
`session.execute` to capture its second argument) and asserts equality
with the pre-change baseline. Spec §5 acceptance criterion 3 calls this
out explicitly.

### References in Codebase

- `parrot/stores/postgres.py:586` — `add_documents` call site.
- `parrot/stores/postgres.py:2551` — `from_documents` call site.
- `parrot/stores/utils/chunking.py:174` — `_create_contextual_text` (the
  late-chunking neighbour-context helper that loses precedence).
- `parrot/stores/abstract.py` — `_apply_contextual_augmentation` (TASK-862).

---

## Acceptance Criteria

- [ ] `add_documents` calls `self._apply_contextual_augmentation(documents)`
      and embeds the result.
- [ ] `content_column` in the inserted row stores RAW `page_content`
      (with null-byte stripping), NOT the augmented text.
- [ ] `metadata_column` in the inserted row carries `contextual_header`
      when the flag is True.
- [ ] `from_documents` re-embeds chunks AND parent document using
      contextual augmentation when the flag is True; uses the
      late-chunking embeddings unchanged when the flag is False.
- [ ] Off-path regression test passes byte-for-byte against the pre-change
      `values` list.
- [ ] Integration tests in spec §4 (Module 3) pass:
      `pytest packages/ai-parrot/tests/integration/stores/test_contextual_pgvector.py -v`
- [ ] `Document.page_content` of each input is unchanged after the call.
- [ ] No new external dependency.
- [ ] `ruff check packages/ai-parrot/src/parrot/stores/postgres.py` passes.

---

## Test Specification

```python
# packages/ai-parrot/tests/integration/stores/test_contextual_pgvector.py
"""Integration tests run against a mocked embedding client and a mocked
session.execute — no real Postgres needed.  A real-DB integration test is
the responsibility of the developer running it locally with a pgvector
container."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import numpy as np

from parrot.stores.models import Document
from parrot.stores.postgres import PgVectorStore


@pytest.fixture
def docs_with_meta():
    return [
        Document(
            page_content="You will receive it on the 15th.",
            metadata={"document_meta": {
                "title": "Handbook", "section": "Pay", "category": "HR",
            }},
        ),
        Document(page_content="Other.", metadata={"document_meta": {}}),
    ]


@pytest.fixture
def store(monkeypatch):
    s = PgVectorStore.__new__(PgVectorStore)
    s.logger = MagicMock()
    s._connected = True
    s._embed_ = MagicMock()
    s._embed_.embed_documents = AsyncMock(
        side_effect=lambda texts: np.zeros((len(texts), 8))
    )
    s.embedding_store = MagicMock()
    s.embedding_store.__table__ = MagicMock(schema="public", name="t")
    s._id_column = "id"
    s._text_column = "text"
    s.table_name = "t"
    s.schema = "public"
    s.dimension = 8
    s._sanitize_metadata = lambda m: m
    s._define_collection_store = MagicMock(return_value=s.embedding_store)
    s.contextual_embedding = False
    s.contextual_template = None
    s.contextual_max_header_tokens = 100
    return s


class TestPgVectorContextual:
    async def test_off_baseline_uses_raw_page_content(self, store, docs_with_meta):
        store.contextual_embedding = False
        with patch("parrot.stores.postgres.insert"):
            with patch.object(store, "session") as sess:
                sess.return_value.__aenter__.return_value.execute = AsyncMock()
                await store.add_documents(docs_with_meta)
        embedded_texts = store._embed_.embed_documents.await_args.args[0]
        assert embedded_texts == ["You will receive it on the 15th.", "Other."]
        for d in docs_with_meta:
            assert "contextual_header" not in d.metadata

    async def test_on_uses_header(self, store, docs_with_meta):
        store.contextual_embedding = True
        from parrot.stores.utils.contextual import DEFAULT_TEMPLATE
        store.contextual_template = DEFAULT_TEMPLATE
        with patch("parrot.stores.postgres.insert"):
            with patch.object(store, "session") as sess:
                sess.return_value.__aenter__.return_value.execute = AsyncMock()
                await store.add_documents(docs_with_meta)
        embedded_texts = store._embed_.embed_documents.await_args.args[0]
        assert embedded_texts[0].startswith("Title: Handbook")
        assert docs_with_meta[0].metadata["contextual_header"].startswith("Title: Handbook")
        assert docs_with_meta[1].metadata["contextual_header"] == ""
```

---

## Agent Instructions

1. **Read the spec** for the precedence rule and acceptance criteria.
2. **Verify TASK-861 and TASK-862 are completed**.
3. **Verify the Codebase Contract** — re-read `postgres.py:586..672` and
   `postgres.py:2551..2700` to confirm the inline patterns are still as listed.
4. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`.
5. **Implement** `add_documents` first (smaller diff), run its test, then
   `from_documents`.
6. **Move this file** to `sdd/tasks/completed/`.
7. **Update index** → `"done"`.

---

## Completion Note

**Completed by**: sdd-worker agent (Claude claude-sonnet-4-5)
**Date**: 2026-04-27
**Notes**: Replaced the inline `texts = [doc.page_content for doc in documents]`
in `add_documents` with `texts_for_embed = self._apply_contextual_augmentation(documents)`.
Added `raw_texts = [doc.page_content for doc in documents]` and updated the
values list-comp to use `raw_texts[i]` for `content_column` (RAW content stored,
not augmented text). In `from_documents`, added the contextual-embedding block:
re-embeds parent document and all chunks when `contextual_embedding=True` (metadata-
header-wins precedence over late-chunking per spec §8 Q3). Both
`_apply_contextual_augmentation` calls in `from_documents` pass `_log=False`; a
single summary log is emitted after the loop instead (review fix). Created
integration test file `tests/integration/stores/test_contextual_pgvector.py`
(4 tests: off-baseline, on-uses-header, raw-content-stored, round-trip).
`ruff check` passes.
**Deviations from spec**: `_log=False` added to suppress 2N per-doc log lines
(identified in code review — improves production observability).
