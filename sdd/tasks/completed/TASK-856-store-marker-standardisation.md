# TASK-856: Marker standardisation in stores (`is_chunk` filter)

**Feature**: FEAT-128 — Parent-Child Retrieval with Composable Parent Searcher
**Spec**: `sdd/specs/parent-child-retrieval.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Module 2 of FEAT-128. Today, parent rows (`is_full_document=True`) sit in
the same vector table as chunks and can compete with them on similarity
score. To keep retrieval precision high, parents must be excluded from the
vector neighbourhood by default.

The plumbing is already partially there: `chunking.py:89` sets
`is_chunk: True` on late-chunking children. This task makes that marker
universal across ingestion paths and adds the corresponding default
exclusion filter in `similarity_search` / `mmr_search`.

Reference: spec §2 (Storage marker standardisation), §3 (Module 2),
§7 (Known Risks #2 — Cold-start re-embedding).

---

## Scope

- Add a default filter to `similarity_search` and `mmr_search` (in both
  `AbstractStore` signature and the postgres concrete implementation)
  that excludes parent rows. Predicate:
  `is_chunk = True OR (is_full_document IS NULL AND document_type IS NULL)`
  — the second branch is the legacy-data backward-compat clause.
- Add a `include_parents: bool = False` kwarg to both methods. When True,
  the filter is bypassed (legacy callers can opt-in to old behaviour).
- Ensure `add_documents` / `from_documents` set
  `metadata['is_chunk'] = True` on every input that does NOT already have
  the marker AND is NOT marked as a parent
  (`is_full_document=True` or `document_type='parent_chunk'`/`'parent'`).
  This is an **idempotent normalisation** — pre-marked inputs are
  untouched.
- Write unit tests that insert mixed chunks + parents and assert default
  filtering behaviour.

**NOT in scope**:
- The `ParentSearcher` package (TASK-855).
- The 3-level hierarchy (TASK-857).
- Bot-side wiring (TASK-858).
- Other store backends (milvus, faiss, bigquery, arango) — postgres only
  per spec §1 Non-Goals.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/stores/abstract.py` | MODIFY | Add `include_parents` kwarg to abstract `similarity_search` signature. Document the new default filter contract. |
| `packages/ai-parrot/src/parrot/stores/postgres.py` | MODIFY | Implement the default filter in concrete `similarity_search` (line 729) and `mmr_search` (line 1797). Normalise `is_chunk: True` on `add_documents` (line 586) and `from_documents` (line 2551). |
| `packages/ai-parrot/tests/stores/test_marker_filter.py` | CREATE | Unit tests for default filter and `include_parents` override. |
| `packages/ai-parrot/tests/stores/test_is_chunk_normalisation.py` | CREATE | Unit tests for idempotent marker normalisation. |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Verified against the codebase on 2026-04-27.

### Verified Imports

```python
from parrot.stores.abstract import AbstractStore           # parrot/stores/abstract.py:17
from parrot.stores.postgres import PgVectorStore            # parrot/stores/postgres.py — class name TBD-verify
from parrot.stores.models import Document                   # parrot/stores/models.py:21
```

### Existing Signatures to Use

```python
# parrot/stores/abstract.py:162
@abstractmethod
async def similarity_search(
    self,
    query: str,
    collection: Union[str, None] = None,
    limit: int = 2,
    similarity_threshold: float = 0.0,
    search_strategy: str = "auto",
    metadata_filters: Union[dict, None] = None,
    **kwargs
) -> list:
    pass

# parrot/stores/abstract.py:206 — add_documents
@abstractmethod
async def add_documents(
    self,
    documents: List[Any],
    collection: Union[str, None] = None,
    **kwargs
) -> None: ...

# parrot/stores/abstract.py:174 — from_documents
@abstractmethod
async def from_documents(
    self,
    documents: List[Any],
    collection: Union[str, None] = None,
    **kwargs
) -> Callable: ...
```

```python
# parrot/stores/postgres.py
async def similarity_search(...) -> list: ...        # line 729
async def mmr_search(...) -> list: ...               # line 1797
async def add_documents(...) -> None: ...            # line 586
async def from_documents(...) -> Callable: ...       # line 2551
# Existing parent insertion path (do NOT change semantics, only ensure
# is_chunk is NOT set on parents):
#     line 2633: 'is_full_document': True,
#     line 2635: 'document_type': 'parent',
# Existing parent retrieval filter precedent at line 2724:
#     doc_filters = {'is_full_document': True}
```

```python
# parrot/stores/utils/chunking.py:89 — already sets is_chunk
'is_chunk': True,                                    # line 89
'parent_document_id': document_id,                   # line 83
```

```python
# parrot/loaders/abstract.py — already sets is_chunk in late-chunking
'is_chunk': True,                                    # line 1091, 1129
'parent_document_id': ...,                           # line 1130
'is_full_document': True,                            # line 1194 (parent assembly)
```

### Does NOT Exist

- ~~A `is_chunk` column on the postgres table~~ — `is_chunk` lives in the
  metadata JSON column. Filter via JSON predicate, not a column.
- ~~`AbstractStore.include_parents` attribute~~ — `include_parents` is a
  per-call kwarg, not stored state.
- ~~A separate "parent table"~~ — parents share the same vector table.
- ~~`document_type='parent_chunk'`~~ — does not exist YET, but the
  exclusion filter MUST treat it as a parent marker (forward-compatibility
  with TASK-857).

---

## Implementation Notes

### Default filter — exact predicate

In SQL terms (postgres metadata JSON):
```sql
WHERE
  (metadata->>'is_chunk')::boolean = true
  OR (
    metadata ? 'is_full_document' = false
    AND metadata ? 'document_type' = false
  )
```

Rationale for the second branch: legacy chunks (ingested before this
feature) have neither `is_chunk` nor any parent marker. They should still
be returned by similarity search so old collections keep working.
Parents (which DO have `is_full_document` or `document_type`) are filtered
out.

### `include_parents=True` semantics

When True, skip BOTH branches of the marker predicate. Other
`metadata_filters` still apply. This is the migration escape hatch for
internal tooling that relied on parents appearing in similarity results.

### Idempotent normalisation in `add_documents` / `from_documents`

```python
def _normalise_chunk_marker(documents):
    """Set metadata['is_chunk']=True on inputs that are clearly chunks.

    Does NOT modify documents that already declare themselves chunks or
    parents. Idempotent: safe to call repeatedly.
    """
    for doc in documents:
        meta = doc.metadata or {}
        is_parent = (
            meta.get('is_full_document') is True
            or meta.get('document_type') in ('parent', 'parent_chunk')
        )
        if 'is_chunk' not in meta and not is_parent:
            meta['is_chunk'] = True
            doc.metadata = meta
```

Apply this BEFORE persisting. Do NOT overwrite `is_chunk` if already set.

### Pattern to Follow

For the postgres SQL changes, mirror the existing JSON-metadata-filter
patterns already in `parrot/stores/postgres.py` (e.g., line 2724
`doc_filters = {'is_full_document': True}`). Extend whatever helper
builds the `metadata_filters` clause to support OR predicates, OR inline
the new marker predicate as raw SQL appended to the WHERE clause.

### Key Constraints

- The marker filter MUST be applied in the SQL WHERE clause, NOT
  post-hoc in Python — post-filtering breaks `limit` semantics and (per
  spec §7 Risk #5) breaks MMR diversification.
- For `mmr_search`: verify the candidate set is filtered, not the result
  set. The candidate fetch already calls `similarity_search` (line 1850),
  so if the filter is correctly applied there, MMR inherits it.
- Backwards compatibility regression: a collection ingested before this
  task (no `is_chunk` markers anywhere) MUST still return its chunks.
- `from_documents` may invoke `add_documents` internally — only
  normalise once. Guard against double-application.

### References in Codebase

- `parrot/stores/postgres.py:1850` — MMR's candidate fetch via
  `similarity_search`. Confirm the filter inherits.
- `parrot/stores/postgres.py:2724` — existing parent-only retrieval
  pattern (the inverse of what this task implements).
- `parrot/stores/utils/chunking.py:89` — existing `is_chunk: True`
  marker on late-chunking children. Confirm this path still works.

---

## Acceptance Criteria

- [ ] `similarity_search(...)` returns ONLY chunk rows when called
      with default args, even on a collection containing both chunks and
      parents.
- [ ] `similarity_search(..., include_parents=True)` returns both chunks
      and parents (regression-compat for legacy callers).
- [ ] `mmr_search(...)` inherits the same default filter (parents are
      not in the candidate set).
- [ ] Legacy chunks (no `is_chunk` markers anywhere) ARE returned by
      default — verified by an explicit regression test.
- [ ] `add_documents` / `from_documents` set `is_chunk=True` on inputs
      that are not already marked (chunks or parents). Idempotent.
- [ ] Pre-marked parents (`is_full_document=True`) are NEVER assigned
      `is_chunk=True`.
- [ ] All unit tests pass: `pytest packages/ai-parrot/tests/stores/test_marker_filter.py packages/ai-parrot/tests/stores/test_is_chunk_normalisation.py -v`
- [ ] No linting errors on modified files.

---

## Test Specification

```python
# packages/ai-parrot/tests/stores/test_marker_filter.py
import pytest
from parrot.stores.models import Document


@pytest.fixture
def mixed_collection_store(pg_store):
    """Store with 3 chunks (is_chunk=True), 2 parents (is_full_document=True),
    and 1 legacy doc (no markers at all)."""
    ...


class TestSimilaritySearchDefaultFilter:
    async def test_default_excludes_parents(self, mixed_collection_store):
        results = await mixed_collection_store.similarity_search(
            "anything", limit=10
        )
        for r in results:
            assert r.metadata.get('is_full_document') is not True
            assert r.metadata.get('document_type') not in ('parent', 'parent_chunk')

    async def test_default_includes_legacy_unmarked(self, mixed_collection_store):
        """Legacy chunks without any markers must still be returned."""
        results = await mixed_collection_store.similarity_search(
            "anything", limit=10
        )
        assert any(
            'is_chunk' not in r.metadata
            and 'is_full_document' not in r.metadata
            for r in results
        )

    async def test_include_parents_kwarg_returns_both(self, mixed_collection_store):
        results = await mixed_collection_store.similarity_search(
            "anything", limit=10, include_parents=True
        )
        assert any(r.metadata.get('is_full_document') is True for r in results)

    async def test_mmr_search_inherits_filter(self, mixed_collection_store):
        results = await mixed_collection_store.mmr_search("anything", limit=10)
        for r in results:
            assert r.metadata.get('is_full_document') is not True


# packages/ai-parrot/tests/stores/test_is_chunk_normalisation.py

class TestAddDocumentsNormalisation:
    async def test_unmarked_doc_gets_is_chunk_true(self, pg_store):
        doc = Document(page_content="text", metadata={"document_id": "x"})
        await pg_store.add_documents([doc])
        # Re-read via similarity_search (default filter must NOT exclude it)
        ...
        assert doc.metadata['is_chunk'] is True

    async def test_already_marked_chunk_untouched(self, pg_store):
        doc = Document(page_content="text",
                       metadata={"document_id": "x", "is_chunk": True})
        await pg_store.add_documents([doc])
        assert doc.metadata['is_chunk'] is True  # unchanged

    async def test_parent_doc_not_marked_as_chunk(self, pg_store):
        doc = Document(page_content="text",
                       metadata={"document_id": "p1", "is_full_document": True})
        await pg_store.add_documents([doc])
        assert 'is_chunk' not in doc.metadata
        assert doc.metadata['is_full_document'] is True

    async def test_parent_chunk_doc_not_marked_as_chunk(self, pg_store):
        doc = Document(page_content="text",
                       metadata={"document_id": "pc1",
                                 "document_type": "parent_chunk"})
        await pg_store.add_documents([doc])
        assert 'is_chunk' not in doc.metadata
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/parent-child-retrieval.spec.md` — focus
   on §2 (Storage marker standardisation), §3 (Module 2), §7 (Risks).
2. **Verify the Codebase Contract** — confirm the line numbers in
   `postgres.py` are still accurate; the file is large and active. If
   line numbers have drifted, locate by symbol name and update the
   contract before coding.
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`.
4. **Implement**: abstract signature first, then postgres concrete, then
   `add_documents`/`from_documents` normalisation, then tests.
5. **Verify** all acceptance criteria — including the legacy-compat
   regression test.
6. **Move this file** to `sdd/tasks/completed/`.
7. **Update index** → `"done"`.
8. **Fill in the Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
