# TASK-857: 3-level hierarchy in late chunking (`document → parent_chunk → child`)

**Feature**: FEAT-128 — Parent-Child Retrieval with Composable Parent Searcher
**Spec**: `sdd/specs/parent-child-retrieval.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-856
**Assigned-to**: unassigned

---

## Context

Module 3 of FEAT-128. When a document exceeds a configurable token
threshold (default 16000 per spec §8 final answer), expanding to the
*entire* document is wasteful: a 50-page handbook becomes 200k tokens of
context. The 3-level hierarchy splits oversized documents into
intermediate **parent chunks** (~4000 tokens each), which become the
parents of small child chunks. Retrieval expansion stops at the
parent_chunk level.

Documents *below* the threshold preserve the existing 2-level path
(`document → child_chunks`) byte-for-byte — strict regression compat.

This task extends `LateChunkingProcessor` and surfaces the new tunables
in `_chunk_with_late_chunking`. It depends on TASK-856 because the new
parent_chunk rows MUST be filtered out of similarity search by default.

Reference: spec §2 (3-level hierarchy at ingestion), §3 (Module 3),
§7 (Risk #1 — Token explosion), §8 (open-question answers).

---

## Scope

- Extend `LateChunkingProcessor` (`parrot/stores/utils/chunking.py:20`)
  with a new method `process_document_three_level(document_text,
  document_id, metadata, parent_chunk_size_tokens,
  parent_chunk_overlap_tokens)` that:
  1. Splits the input into parent chunks (semantic-aware where possible,
     falling back to token-window split).
  2. For each parent chunk, runs the existing
     `process_document_late_chunking` with the parent_chunk's UUID as
     `document_id`, producing child `ChunkInfo` records whose
     `parent_document_id` points to the parent_chunk's UUID.
  3. Returns parent_chunk Documents (with metadata
     `document_type='parent_chunk'`, `is_chunk=False`,
     `source_document_id=<original doc id>`) AND the children.
- Modify `_chunk_with_late_chunking`
  (`parrot/loaders/abstract.py:1143`) to accept three new kwargs:
  - `parent_chunk_threshold_tokens: int = 16000`  (per §8 update)
  - `parent_chunk_size_tokens: int = 4000`
  - `parent_chunk_overlap_tokens: int = 200`
- Route oversized documents (token count > threshold) through the new
  3-level path. Smaller documents continue through the existing 2-level
  path with byte-equal behaviour.
- For 3-level docs, do NOT store the original document as a
  parent (would defeat the size-cap intent). Only parent_chunks and
  children are persisted.
- Write unit tests covering: split correctness, threshold gating,
  metadata shape on parent_chunks, regression on the 2-level path.

**NOT in scope**:
- Bot-side wiring (TASK-858).
- Changes to non-late-chunking loaders (e.g., naïve recursive splitters).
  Spec §1 Non-Goals limits the marker change to "consistently emit
  `is_chunk: True`", which TASK-856 already covers.
- Modifications to `_from_db` or chatbot.yaml exposure of these knobs.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/stores/utils/chunking.py` | MODIFY | Extend `LateChunkingProcessor` with `process_document_three_level`. |
| `packages/ai-parrot/src/parrot/loaders/abstract.py` | MODIFY | Add the three new kwargs to `_chunk_with_late_chunking` (line 1143) and route by token count. |
| `packages/ai-parrot/tests/stores/utils/test_three_level_chunking.py` | CREATE | Unit tests for the new path. |
| `packages/ai-parrot/tests/loaders/test_late_chunking_threshold.py` | CREATE | Tests that gate by token count and verify byte-equal regression on the 2-level path. |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Verified against the codebase on 2026-04-27.

### Verified Imports

```python
import uuid
import numpy as np
from typing import Dict, List, Optional, Tuple
from parrot.stores.models import Document                        # parrot/stores/models.py:21
from parrot.stores.utils.chunking import (                        # parrot/stores/utils/chunking.py
    LateChunkingProcessor,                                        # line 20
    ChunkInfo,                                                    # line 8
)
```

### Existing Signatures to Use

```python
# parrot/stores/utils/chunking.py:8
@dataclass
class ChunkInfo:
    chunk_id: str
    parent_document_id: str          # link from child to parent
    chunk_index: int
    chunk_text: str
    start_position: int
    end_position: int
    chunk_embedding: np.ndarray
    metadata: Dict[str, Any]

# parrot/stores/utils/chunking.py:20
class LateChunkingProcessor:
    def __init__(self, vector_store, chunk_size=8192, chunk_overlap=200,
                 preserve_sentences=True, min_chunk_size=100): ...

    async def process_document_late_chunking(           # line 42
        self,
        document_text: str,
        document_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Tuple[np.ndarray, List[ChunkInfo]]: ...

# Existing child-chunk metadata pattern (line 83-89):
#     'parent_document_id': document_id
#     'is_chunk': True
```

```python
# parrot/loaders/abstract.py:1143
async def _chunk_with_late_chunking(
    self,
    documents: List[Document],
    vector_store=None,
    store_full_document: bool = True,
) -> List[Document]: ...

# Child assembly at line 1129-1130:
#     'is_chunk': True
#     'parent_document_id': doc.metadata.get('document_id', f"doc_{uuid.uuid4().hex[:8]}")
# Parent assembly at line 1190-1196:
#     'is_full_document': True
#     'document_type': 'parent'
```

### Does NOT Exist

- ~~`LateChunkingProcessor.process_document_three_level`~~ — created by
  THIS task.
- ~~A `parent_chunks` table~~ — parent_chunks live in the SAME vector
  table as chunks and full-document parents. They are distinguished by
  `metadata['document_type']='parent_chunk'`.
- ~~`document_type='parent_chunk'`~~ — this VALUE does not yet exist
  anywhere in the codebase. THIS task introduces it.
- ~~A token counter utility~~ — verify which counter the project uses
  (look for `tiktoken` usage near line 1143 of `loaders/abstract.py` or
  in `chunking.py`). Use the existing one. Do NOT add a new tokenizer
  dependency.
- ~~`source_document_id` field~~ — new metadata field on parent_chunks.
  For audit/telemetry only; retrieval does not use it (spec §7).

---

## Implementation Notes

### Splitting strategy for parent chunks

Use the existing chunking helpers in `LateChunkingProcessor` for
sentence-aware splitting where available. Approximate algorithm:

```python
async def process_document_three_level(
    self,
    document_text: str,
    document_id: str,
    metadata: Optional[Dict[str, Any]] = None,
    parent_chunk_size_tokens: int = 4000,
    parent_chunk_overlap_tokens: int = 200,
) -> Tuple[List[Document], List[ChunkInfo]]:
    """
    Split oversized doc into parent_chunks of ~parent_chunk_size_tokens,
    then run late chunking inside each parent_chunk.

    Returns:
        parent_chunks: list[Document] with metadata
            {document_type: 'parent_chunk', is_chunk: False,
             source_document_id: <doc id>, parent_chunk_index: i, ...}
        children: list[ChunkInfo] whose parent_document_id points to a
            parent_chunk's UUID (NOT the original document_id).
    """
    parent_chunks: list[Document] = []
    all_children: list[ChunkInfo] = []
    for i, parent_text in enumerate(self._split_to_parent_chunks(
        document_text, parent_chunk_size_tokens, parent_chunk_overlap_tokens
    )):
        parent_chunk_id = str(uuid.uuid4())
        parent_doc = Document(
            page_content=parent_text,
            metadata={
                **(metadata or {}),
                'document_id': parent_chunk_id,
                'document_type': 'parent_chunk',
                'is_chunk': False,
                'source_document_id': document_id,
                'parent_chunk_index': i,
            },
        )
        parent_chunks.append(parent_doc)
        _, children = await self.process_document_late_chunking(
            document_text=parent_text,
            document_id=parent_chunk_id,
            metadata={**(metadata or {}),
                      'parent_chunk_index': i,
                      'source_document_id': document_id},
        )
        all_children.extend(children)
    return parent_chunks, all_children
```

`_split_to_parent_chunks` should:
1. Prefer paragraph/sentence boundaries (re-use whatever
   `preserve_sentences=True` already provides in the existing splitter).
2. Apply `parent_chunk_overlap_tokens` overlap between adjacent parent
   chunks for context bleeding.
3. Token-count via the existing tokenizer (find it; do not add a new
   one).

### Routing in `_chunk_with_late_chunking`

```python
async def _chunk_with_late_chunking(
    self,
    documents: List[Document],
    vector_store=None,
    store_full_document: bool = True,
    parent_chunk_threshold_tokens: int = 16000,    # NEW
    parent_chunk_size_tokens: int = 4000,           # NEW
    parent_chunk_overlap_tokens: int = 200,         # NEW
) -> List[Document]:
    out = []
    for doc in documents:
        token_count = self._count_tokens(doc.page_content)
        if token_count > parent_chunk_threshold_tokens:
            # 3-level path: parents are parent_chunks; doc itself NOT stored
            parent_chunks, children = await processor.process_document_three_level(
                doc.page_content,
                doc.metadata.get('document_id', f"doc_{uuid.uuid4().hex[:8]}"),
                doc.metadata,
                parent_chunk_size_tokens=parent_chunk_size_tokens,
                parent_chunk_overlap_tokens=parent_chunk_overlap_tokens,
            )
            out.extend(parent_chunks)
            out.extend(self._children_to_documents(children))
        else:
            # 2-level path: existing behaviour, byte-equal
            ...
    return out
```

### Default threshold = 16000 (per §8)

Spec §8 open-question answer (Jesus Lara): "starts in 16000 and do some
benchmarks". Default kwarg value MUST be `16000`, not the original
`8000` shown in §3 prose. Document this discrepancy in the task
completion note.

### Key Constraints

- The 2-level path MUST be byte-equal regression: same `document_id` on
  parents, same `is_full_document=True, document_type='parent'`, same
  child `parent_document_id`. Add an explicit regression test.
- `is_chunk=False` MUST be set explicitly on parent_chunk Documents
  (not just absent) so TASK-856's normalisation doesn't accidentally
  flip them.
- `parent_chunk_overlap_tokens` MUST be < `parent_chunk_size_tokens`.
  Validate at the start of `process_document_three_level`; raise
  `ValueError` with a clear message.
- The original document's `document_id` is preserved in parent_chunks
  via `source_document_id` (NOT `parent_document_id` — that is reserved
  for the child→parent link). Spec §7.
- Async throughout. Use `self.logger` for INFO-level summaries
  ("Document X split into N parent_chunks of avg M tokens").

### References in Codebase

- `parrot/stores/utils/chunking.py:42` —
  `process_document_late_chunking` (the inner call for each
  parent_chunk).
- `parrot/loaders/abstract.py:1129-1130` — existing child metadata
  pattern.
- `parrot/loaders/abstract.py:1190-1196` — existing parent metadata
  pattern (preserved unchanged in 2-level path).

---

## Acceptance Criteria

- [ ] `LateChunkingProcessor.process_document_three_level(...)` exists
      and returns `(parent_chunks: list[Document], children:
      list[ChunkInfo])`.
- [ ] Each parent_chunk has metadata `document_type='parent_chunk'`,
      `is_chunk=False`, `source_document_id=<original_doc_id>`, and a
      unique `document_id`.
- [ ] Each child's `parent_document_id` points to the parent_chunk's
      UUID, NOT the original document's id.
- [ ] `parent_chunk_overlap_tokens >= parent_chunk_size_tokens` raises
      `ValueError` at call time.
- [ ] `_chunk_with_late_chunking` accepts the three new kwargs with
      defaults `(16000, 4000, 200)`.
- [ ] Documents above threshold use 3-level path; those at-or-below use
      2-level. Regression test asserts the 2-level path produces output
      byte-equal to the pre-feature behaviour.
- [ ] Original document is NOT stored as a parent when the 3-level path
      is taken.
- [ ] All unit tests pass: `pytest packages/ai-parrot/tests/stores/utils/test_three_level_chunking.py packages/ai-parrot/tests/loaders/test_late_chunking_threshold.py -v`
- [ ] No new external dependencies introduced.

---

## Test Specification

```python
# packages/ai-parrot/tests/stores/utils/test_three_level_chunking.py
import pytest
from parrot.stores.utils.chunking import LateChunkingProcessor


@pytest.fixture
def processor(mock_vector_store):
    return LateChunkingProcessor(vector_store=mock_vector_store)


class TestThreeLevelChunking:
    async def test_split_into_multiple_parent_chunks(self, processor):
        long_text = "..." * 6000  # > 16k tokens
        parents, children = await processor.process_document_three_level(
            document_text=long_text,
            document_id="doc-large-1",
            metadata={"title": "Long"},
            parent_chunk_size_tokens=4000,
            parent_chunk_overlap_tokens=200,
        )
        assert len(parents) >= 3
        assert all(p.metadata['document_type'] == 'parent_chunk' for p in parents)
        assert all(p.metadata['is_chunk'] is False for p in parents)
        assert all(p.metadata['source_document_id'] == 'doc-large-1' for p in parents)

    async def test_children_link_to_parent_chunks_not_doc(self, processor):
        long_text = "..." * 6000
        parents, children = await processor.process_document_three_level(
            long_text, "doc-large-1", {},
        )
        parent_ids = {p.metadata['document_id'] for p in parents}
        for child in children:
            assert child.parent_document_id in parent_ids
            assert child.parent_document_id != 'doc-large-1'

    async def test_overlap_validation(self, processor):
        with pytest.raises(ValueError, match="overlap"):
            await processor.process_document_three_level(
                "x" * 100, "doc-1", {},
                parent_chunk_size_tokens=200,
                parent_chunk_overlap_tokens=300,
            )


# packages/ai-parrot/tests/loaders/test_late_chunking_threshold.py

class TestLateChunkingThresholdRouting:
    async def test_small_doc_uses_2level_path(self, loader):
        small = Document(page_content="..." * 500,  # ~3k tokens
                         metadata={"document_id": "small-1"})
        out = await loader._chunk_with_late_chunking([small])
        # Expect a parent with is_full_document=True (existing pattern)
        parents = [d for d in out if d.metadata.get('is_full_document') is True]
        chunks = [d for d in out if d.metadata.get('is_chunk') is True]
        assert len(parents) == 1
        assert all(c.metadata['parent_document_id'] == 'small-1' for c in chunks)

    async def test_large_doc_uses_3level_path(self, loader):
        large = Document(page_content="..." * 6000,  # > 16k tokens
                         metadata={"document_id": "large-1"})
        out = await loader._chunk_with_late_chunking([large])
        parent_chunks = [d for d in out
                          if d.metadata.get('document_type') == 'parent_chunk']
        full_docs = [d for d in out if d.metadata.get('is_full_document') is True]
        chunks = [d for d in out if d.metadata.get('is_chunk') is True]
        assert len(parent_chunks) >= 3
        assert full_docs == []  # original doc NOT stored as parent in 3-level
        # children link to parent_chunks, not to 'large-1'
        parent_chunk_ids = {pc.metadata['document_id'] for pc in parent_chunks}
        assert all(c.metadata['parent_document_id'] in parent_chunk_ids for c in chunks)

    async def test_2level_byte_equal_regression(self, loader, snapshot):
        """Output for a small doc must match the pre-feature snapshot
        byte-for-byte (markers, IDs, ordering)."""
        small = Document(page_content="...stable test text...",
                         metadata={"document_id": "stable-id"})
        out = await loader._chunk_with_late_chunking([small])
        snapshot.assert_match(out)
```

---

## Agent Instructions

When you pick up this task:

1. **Confirm dependency**: TASK-856 must be in `sdd/tasks/completed/`.
2. **Read the spec** at `sdd/specs/parent-child-retrieval.spec.md` —
   focus on §2 (Architectural Design), §3 (Module 3), §7 (Risks),
   §8 (open-question answers — note the **16000 default**).
3. **Verify the Codebase Contract** — locate the existing tokenizer
   (likely `tiktoken` or similar). Confirm line numbers in
   `loaders/abstract.py` and `stores/utils/chunking.py`.
4. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`.
5. **Implement** in this order: token counter helper, parent-chunk
   splitter, `process_document_three_level`, `_chunk_with_late_chunking`
   routing, tests.
6. **Verify** the regression test on the 2-level path FIRST — it must
   pass before claiming the task done.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
