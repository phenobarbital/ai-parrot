# Feature Specification: Parent-Child Retrieval with Composable Parent Searcher

**Feature ID**: FEAT-128
**Date**: 2026-04-27
**Author**: Jesus Lara
**Status**: draft
**Target version**: ai-parrot next minor

---

## 1. Motivation & Business Requirements

### Problem Statement

Today's retrieval pipeline embeds and searches over chunks of approximately
512 tokens (`context_search_limit=10`, `context_score_threshold=0.7`). For
queries whose answer naturally spans multiple chunks of the same source
paragraph — e.g. *"¿cómo recibiré mi paga?"* against a handbook section that
explains payroll over 3–4 paragraphs that the chunker has split — the LLM
receives several disconnected fragments and synthesises a worse answer than
if it had received the original paragraph in one piece.

The standard fix is **parent-child / small-to-big retrieval**: embed and
search over small chunks (precise) but return their **parent** document or
parent chunk (full context) to the LLM. The chunk is the *index*; the parent
is the *payload*.

There is significant plumbing already in place:

- Every chunk emitted by `AbstractLoader` carries
  `metadata['parent_document_id']` pointing to its source document
  (`parrot/loaders/abstract.py:1130`, `parrot/stores/utils/chunking.py:11`).
- `LateChunkingProcessor` (`parrot/stores/utils/chunking.py:20`) already
  stores the full document alongside chunks when `store_full_document=True`
  is set (default), marking the parent row with `is_full_document: True` and
  `document_type: 'parent'`
  (`parrot/loaders/abstract.py:1190-1196`,
  `parrot/stores/postgres.py:2629-2635`).
- `PgVectorStore` already filters parent rows with
  `doc_filters = {'is_full_document': True}` in at least one code path
  (`parrot/stores/postgres.py:2724`).

What is missing is the **retrieval-side** consumption of this plumbing:

1. There is no flag on `BaseBot` / `_build_vector_context` that, given a list
   of matched child chunks, fetches their parents, deduplicates by parent ID,
   and substitutes parents for children in the LLM context.
2. Parent rows are not consistently filtered out of similarity search — they
   currently sit in the same vector space as chunks and can compete with
   them on score.
3. When a document is too large to send as a single parent (a 50-page
   handbook section), there is no agreed split into intermediate "parent
   chunks" to keep prompt sizes reasonable. We need a 3-level hierarchy:
   `document → parent_chunk → child_chunk`, with retrieval traversing
   `child → parent_chunk` (not `child → full_document`) above a configurable
   size threshold.
4. Where the parent **lives** (same vector table today, separate table or
   object store tomorrow) should be configurable without changing the
   retrieval call site. We want a composable `ParentSearcher` interface.

This feature wires retrieval-side parent-child while keeping current ingestion
behaviour stable, with the caveat that it requires marking chunks as such
(`is_chunk: True`) so similarity search can exclude parents by default.

### Goals

1. Introduce a `ParentSearcher` abstraction (`parrot/stores/parents/`) with
   one default implementation `InTableParentSearcher` that fetches parent
   rows from the same vector table by `document_id IN (...)` filtered to
   `is_full_document=True OR document_type='parent_chunk'`. The interface is
   composable so a future `S3ParentSearcher` or `SeparateTableParentSearcher`
   slots in without touching the bot.
2. Add `expand_to_parent: bool = False` configuration to `AbstractBot`
   (constructor kwarg), with a per-call override. When True,
   `_build_vector_context` post-processes retrieval results: groups children
   by `parent_document_id`, deduplicates, fetches parents via
   `self.parent_searcher`, and returns parents (in order of best child score)
   instead of children.
3. Standardise the in-table marker convention so similarity_search excludes
   parents by default: chunks carry `is_chunk: True`, parents carry
   `is_full_document: True` or `document_type: 'parent_chunk'`. The default
   filter on `similarity_search` is `is_chunk=True OR is_full_document is
   missing` (covers legacy data).
4. Define and implement the **3-level hierarchy** for large documents.
   Documents above a configurable token threshold (default 8000) are split
   semantically into parent chunks of approximately 4000 tokens (with
   overlap), which become the parents of the small child chunks. Retrieval
   expansion stops at the parent_chunk level, never returning the entire
   original document for these cases.
5. Deduplication by `parent_document_id`: when N children share a parent,
   the parent is fetched and emitted **once**, ranked by the best child's
   score. Order across distinct parents follows the best child of each.
6. Backward compatibility: chunks ingested before this feature without a
   `parent_document_id`, or whose parent row was never stored, fall through
   to the child as-is with a single DEBUG log line. No errors raised.
7. Bot-level **and** per-call configuration. The bot owns the default
   (`expand_to_parent` and the choice of `ParentSearcher`); individual calls
   can override with `expand_to_parent=False` for ad-hoc precision queries
   or `=True` to opt-in for a specific call when the bot default is False.

### Non-Goals (explicitly out of scope)

- **Re-ingesting existing collections** with the new parent-chunk hierarchy.
  Migrations are an ops concern handled by a separate procedure.
- **Hybrid lexical+dense retrieval** (BM25/ColBERT). Out of scope — for the
  target use cases (consistent corpora: handbooks, policies, training
  material), parent-child plus the FEAT-126 cross-encoder reranker is
  sufficient. BM25 hybrid is deferred.
- **Cross-encoder reranking** itself — that is FEAT-126. This feature
  composes with it: the reranker (when configured) ranks the **child**
  candidates, and parent expansion happens after reranking on the top-K
  reranked children, so we expand the *right* parents.
- **Storing parents outside the vector table** in v1. The composable
  `ParentSearcher` interface allows it later without changing call sites,
  but only `InTableParentSearcher` ships now.
- **Modifying `AbstractLoader.create_metadata`** beyond ensuring the
  `is_chunk: True` marker is consistently emitted on chunks. Other metadata
  shape changes belong to `ai-parrot-loaders-metadata-standarization`.
- **Exposing `ParentSearcher` selection in the DB-driven chatbot config**
  (`_from_db` path). v1 is constructor-injection only; the `_from_db`
  surface can be extended later.

---

## 2. Architectural Design

### Overview

Two pieces:

**A. Storage marker standardisation (small).** Ensure every ingestion path
marks chunks with `is_chunk: True` and parents with `is_full_document: True`
(or `document_type: 'parent_chunk'` for intermediate parents). The
`similarity_search` default filter excludes parents from the vector
neighbourhood so they never compete with chunks. This is a **minimal
`ALTER`-equivalent change**: the metadata is already in the JSON column on
postgres; the work is to make the convention universal and to add the
exclusion filter in `similarity_search`.

**B. Retrieval-side expansion (the core of this spec).** A new
`ParentSearcher` interface plus the `InTableParentSearcher` default. The bot
holds an instance. `AbstractBot._build_vector_context` gains a post-step
that, when `expand_to_parent` is True:

1. Takes the retrieval results (already optionally reranked by FEAT-126).
2. Extracts the unique `parent_document_id` set, preserving the order of
   their best child match.
3. Calls `parent_searcher.fetch(parent_ids)` to retrieve parent payloads.
4. Builds the LLM context from parents (deduped, ordered) instead of
   children.
5. On any miss (parent not found, searcher raised), logs DEBUG, falls
   through to the child for that group.

**3-level hierarchy at ingestion** (independent of the searcher): when a
document exceeds `parent_chunk_threshold_tokens` (default 8000), the loader
splits it into parent chunks of approximately `parent_chunk_size_tokens`
(default 4000) with `parent_chunk_overlap_tokens` (default 200) overlap, and
each child chunk's `parent_document_id` points to the **parent_chunk** ID,
not to the original document. The original document is not stored as a
parent in this case (it is too large). For documents below the threshold,
the existing 2-level `chunk → full_document` flow is preserved.

### Component Diagram

```
                        ┌──────────────────────────────────────┐
                        │  Loader.split_for_embedding()        │
                        │  - if doc.size > threshold:          │
                        │      doc → parent_chunks (4k each)   │
                        │      parent_chunk → child_chunks     │
                        │  - else:                             │
                        │      doc → child_chunks              │
                        │      (doc is the parent)             │
                        └──────────────────┬───────────────────┘
                                           │
                                           ▼
                        ┌──────────────────────────────────────┐
                        │  Store.add_documents(...)            │
                        │  - chunks marked is_chunk=True       │
                        │  - parents marked is_full_document=  │
                        │    True or document_type=parent_chunk│
                        └──────────────────────────────────────┘

  ── retrieval time ──

     ┌─────────────────────────────┐
     │ store.similarity_search     │   default filter: is_chunk=True
     │ → list[SearchResult]        │   (parents excluded from neighbourhood)
     └────────────┬────────────────┘
                  │
                  ▼
     ┌─────────────────────────────┐
     │ FEAT-126 reranker (optional)│   reranks children
     └────────────┬────────────────┘
                  │
                  ▼ (top-K children)
     ┌─────────────────────────────┐
     │ if expand_to_parent:         │
     │   group by parent_id, keep   │
     │   best score per group       │
     │   parent_searcher.fetch(ids) │
     │   substitute children with   │
     │   parents (dedupe, ordered)  │
     └────────────┬────────────────┘
                  │
                  ▼
     ┌─────────────────────────────┐
     │ Context assembly → LLM      │
     └─────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractBot` (`parrot/bots/abstract.py:144`) | extends | Adds `self.parent_searcher`, `self.expand_to_parent` (default False), constructor kwargs. |
| `AbstractBot._build_vector_context` (`abstract.py:2239`) | modifies | Post-rerank parent expansion when flag is True. Composes cleanly with FEAT-126. |
| `AbstractBot.get_vector_context` (`abstract.py:1587`) | modifies | Same hook applied here. |
| `AbstractStore.similarity_search` | modifies | Adds default filter `is_chunk=True`. Existing callers can override with `include_parents=True` to get the legacy behaviour. |
| `parrot/stores/utils/chunking.py:LateChunkingProcessor` (line 20) | extends | Adds optional 3-level hierarchy when document exceeds size threshold. |
| `parrot/loaders/abstract.py:_chunk_with_late_chunking` (line 1143) | modifies | Surfaces the threshold + parent-chunk size kwargs and routes large docs through the new 3-level path. Existing 2-level path preserved when threshold not exceeded. |
| `metadata['parent_document_id']` (already populated) | reused | The existing field is the link from child to parent. No schema change. |
| `metadata['is_full_document']` / `document_type` | reused + new | Existing for full-doc parents; `document_type='parent_chunk'` is new for intermediate parents. |
| `metadata['is_chunk']` | new convention | Already set in `chunking.py:89` via `is_chunk: True`. This spec ensures it is universal across loaders, not just late-chunking. |

### Data Models

```python
# parrot/stores/parents/abstract.py
from abc import ABC, abstractmethod
from parrot.stores.models import Document


class AbstractParentSearcher(ABC):
    """Composable strategy for fetching parent documents by ID."""

    @abstractmethod
    async def fetch(self, parent_ids: list[str]) -> dict[str, Document]:
        """Fetch parents by ID. Missing IDs are simply absent from the result.

        Implementations MUST NOT raise on individual misses — return what was
        found. Raising is reserved for infrastructure failures (connection
        loss, etc.), not data gaps.
        """

    async def health_check(self) -> bool:
        """Optional readiness probe. Default: True."""
        return True
```

```python
# parrot/stores/parents/in_table.py
class InTableParentSearcher(AbstractParentSearcher):
    """Fetch parents from the same vector table by metadata filter.

    Default for postgres / pgvector. Issues a single SQL query:
        SELECT * FROM <table>
        WHERE document_id IN (:ids)
          AND (is_full_document = true OR document_type = 'parent_chunk')
    """

    def __init__(self, store: AbstractStore):
        self.store = store
```

### New Public Interfaces

```python
# AbstractBot constructor gains:
self.parent_searcher: Optional[AbstractParentSearcher] = kwargs.get(
    "parent_searcher", None
)
self.expand_to_parent: bool = kwargs.get("expand_to_parent", False)

# get_vector_context / _build_vector_context get a per-call override:
async def _build_vector_context(
    self,
    question: str,
    ...,
    expand_to_parent: Optional[bool] = None,    # None → use bot default
    ...,
):
    ...
```

```python
# parrot/loaders/abstract.py — _chunk_with_late_chunking gains:
async def _chunk_with_late_chunking(
    self,
    documents: List[Document],
    vector_store=None,
    store_full_document: bool = True,
    parent_chunk_threshold_tokens: int = 8000,        # NEW
    parent_chunk_size_tokens: int = 4000,             # NEW
    parent_chunk_overlap_tokens: int = 200,           # NEW
) -> List[Document]:
    ...
```

---

## 3. Module Breakdown

### Module 1: `parrot/stores/parents/` package
- **Path**: `packages/ai-parrot/src/parrot/stores/parents/__init__.py`,
  `abstract.py`, `in_table.py`.
- **Responsibility**: Export `AbstractParentSearcher`,
  `InTableParentSearcher`. The abstract base is stdlib-only; the in-table
  impl depends on `AbstractStore` for the underlying connection.
- **Depends on**: `parrot.stores.abstract.AbstractStore`,
  `parrot.stores.models.Document`.

### Module 2: Marker standardisation in stores
- **Path**: `packages/ai-parrot/src/parrot/stores/abstract.py`,
  `parrot/stores/postgres.py`.
- **Responsibility**:
  - Add a default filter `is_chunk=True` to `similarity_search` and
    `mmr_search`. Add `include_parents: bool = False` kwarg to override.
  - Ensure `add_documents` / `from_documents` set `metadata['is_chunk'] =
    True` on every non-parent input that does not already have the marker
    (idempotent normalisation).
- **Depends on**: stdlib + existing store code.

### Module 3: 3-level hierarchy in late chunking
- **Path**: `packages/ai-parrot/src/parrot/stores/utils/chunking.py`,
  `parrot/loaders/abstract.py:_chunk_with_late_chunking` (line 1143).
- **Responsibility**:
  - Extend `LateChunkingProcessor` with a `process_document_three_level`
    method that splits docs above the threshold into parent chunks first,
    then child chunks per parent. Each child's `parent_document_id` points
    to the parent_chunk's UUID, not the original document's.
  - Mark parent_chunks with `document_type: 'parent_chunk'` and `is_chunk:
    False`. Original document is NOT stored when 3-level path is used.
  - For docs below threshold, behaviour is unchanged.
- **Depends on**: Module 2 (so the new parent_chunks are filtered out of
  similarity search by default).

### Module 4: Bot-side wiring
- **Path**: `packages/ai-parrot/src/parrot/bots/abstract.py`.
- **Responsibility**:
  - Add `self.parent_searcher` and `self.expand_to_parent` in `__init__`
    (next to `context_search_limit`, around line 387).
  - In `_build_vector_context` (line 2239) and `get_vector_context` (line
    1587), after retrieval (and after FEAT-126 reranking when present),
    when `expand_to_parent` is True:
    1. Group results by `metadata['parent_document_id']`. Drop entries
       without one (legacy/partial data) — keep them as-is in the result.
    2. For each group, retain best score and the original child as fallback.
    3. Call `self.parent_searcher.fetch(unique_parent_ids)`.
    4. Substitute each group's child with its parent in the result list,
       in the order of best-child-score across groups. Children whose
       parent could not be fetched are kept verbatim.
  - Per-call `expand_to_parent` override resolution: explicit kwarg wins,
    then bot default, then `False`.
- **Depends on**: Modules 1, 2.

### Module 5: Tests
- **Path**: `packages/ai-parrot/tests/unit/stores/parents/`,
  `tests/unit/bots/test_parent_expansion.py`,
  `tests/integration/stores/test_parent_child_pgvector.py`.
- **Responsibility**: See §4.

### Module 6: Documentation
- **Path**: `docs/parent-child-retrieval.md`.
- **Responsibility**: Architecture, when to enable, the 3-level hierarchy
  defaults, composing with FEAT-126 reranker, the migration warning for
  collections ingested before this feature.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_abstract_parent_searcher_is_abc` | 1 | Cannot instantiate directly. |
| `test_in_table_searcher_fetches_existing_parents` | 1 | Given parent IDs that exist, returns them keyed by ID. |
| `test_in_table_searcher_silently_skips_missing` | 1 | Missing IDs are absent from the result, no exception. |
| `test_in_table_searcher_filters_by_parent_markers` | 1 | A query that includes a chunk's ID returns nothing (chunks are not parents). |
| `test_similarity_search_excludes_parents_by_default` | 2 | Insert mixed chunks + parents; `similarity_search` returns only chunks. |
| `test_similarity_search_include_parents_kwarg` | 2 | `include_parents=True` returns both — backward compat for existing callers. |
| `test_three_level_hierarchy_split` | 3 | Doc of 12k tokens splits into 3 parent_chunks; each has multiple child chunks; child `parent_document_id` points to its parent_chunk's UUID, not the doc. |
| `test_three_level_threshold_respected` | 3 | Doc of 4k tokens uses 2-level path (doc is the parent); no parent_chunks created. |
| `test_bot_expand_to_parent_groups_and_dedups` | 4 | 5 children with 2 distinct parent_ids → 2 parents in final context, ordered by best child score. |
| `test_bot_expand_to_parent_per_call_override` | 4 | Bot default True, call passes `expand_to_parent=False` → children returned, parents not fetched. |
| `test_bot_expand_to_parent_missing_parent_falls_through` | 4 | Group whose parent cannot be fetched falls back to the original child without raising. |
| `test_bot_no_parent_searcher_no_op` | 4 | `expand_to_parent=True` but `parent_searcher=None` → log WARNING once, return children. |
| `test_bot_legacy_chunks_without_parent_id` | 4 | Mixed batch with some children missing `parent_document_id`: those pass through, others expand. |

### Integration Tests

| Test | Description |
|---|---|
| `test_pgvector_end_to_end_2level` | Ingest 5 small docs (<8k tokens each) with default flags, query, expand to parents, assert each retrieved context is the original document. |
| `test_pgvector_end_to_end_3level` | Ingest 1 large doc (~16k tokens), assert 4 parent_chunks created, query for content in middle parent_chunk, assert that single parent_chunk is returned (not the full doc). |
| `test_pgvector_compose_with_reranker` | With FEAT-126 reranker configured AND `expand_to_parent=True`: reranker reorders children, parent expansion runs on the reranked top-K, dedupe by parent works correctly. |
| `test_basebot_ask_with_parent_expansion` | End-to-end `BaseBot.ask()` against a mock LLM; assert that the answer was synthesised from a parent-sized context (longer than any individual chunk). |

### Test Data / Fixtures

```python
@pytest.fixture
def small_doc():
    """Below 8k threshold — 2-level path (doc is its own parent)."""
    return Document(
        page_content="...~3000 tokens of cohesive text...",
        metadata={"document_id": "doc-small-1", "title": "Small Handbook"},
    )

@pytest.fixture
def large_doc():
    """Above 8k threshold — 3-level path (doc → parent_chunks → children)."""
    return Document(
        page_content="...~16000 tokens of cohesive text...",
        metadata={"document_id": "doc-large-1", "title": "Long Policy"},
    )

@pytest.fixture
def in_memory_parent_searcher(pg_store):
    return InTableParentSearcher(store=pg_store)
```

---

## 5. Acceptance Criteria

This feature is complete when ALL of the following are true:

- [ ] `parrot/stores/parents/` package exists with `AbstractParentSearcher`
      and `InTableParentSearcher`.
- [ ] `AbstractBot` accepts `parent_searcher` and `expand_to_parent`
      constructor kwargs; `expand_to_parent` defaults to `False` (opt-in).
- [ ] `_build_vector_context` and `get_vector_context` perform parent
      expansion after retrieval (and after FEAT-126 reranking when present),
      with dedupe by `parent_document_id` and ordering by best child score.
- [ ] `similarity_search` and `mmr_search` filter out parent rows by
      default (`is_chunk=True`); `include_parents=True` restores legacy
      behaviour.
- [ ] `LateChunkingProcessor` supports the 3-level hierarchy when document
      tokens exceed `parent_chunk_threshold_tokens` (default 8000), splitting
      into parent_chunks of `parent_chunk_size_tokens` (default 4000) with
      `parent_chunk_overlap_tokens` (default 200) overlap.
- [ ] Documents below the threshold use the existing 2-level path
      unchanged. Regression test asserts byte-equal behaviour.
- [ ] Legacy chunks without `parent_document_id` pass through with a single
      DEBUG log line, never an error.
- [ ] Per-call `expand_to_parent` override resolution: explicit kwarg →
      bot default → `False`.
- [ ] Composes cleanly with FEAT-126: when both a reranker and a
      parent_searcher are configured, the reranker runs on children, parent
      expansion runs on the reranker's top-K. Integration test verifies.
- [ ] `BaseBot.ask()` and `BaseBot.conversation()` produce identical output
      to today when `expand_to_parent=False` (regression snapshot test).
- [ ] No new external dependencies. Only stdlib + existing project deps.
- [ ] Documentation page in `docs/parent-child-retrieval.md` covers
      enabling, hierarchy threshold, FEAT-126 composition, and the migration
      warning for pre-existing collections.
- [ ] Performance budget: parent expansion adds ≤ 50 ms P95 to a request
      with 10 unique parents, on the in-table searcher (single SQL round
      trip). Documented in benchmark output, not enforced by CI.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports

```python
from parrot.bots.abstract import AbstractBot                     # parrot/bots/abstract.py:144
from parrot.stores.abstract import AbstractStore                 # parrot/stores/abstract.py:17
from parrot.stores.models import Document, SearchResult          # parrot/stores/models.py:21,7
from parrot.stores.utils.chunking import (
    LateChunkingProcessor, ChunkInfo,                            # parrot/stores/utils/chunking.py:20,8
)
```

### Existing Class Signatures (re-verified 2026-04-27)

```python
# parrot/bots/abstract.py:144
class AbstractBot(VectorInterface, ...):
    self.context_search_limit: int = ...                # line 387
    self.context_score_threshold: float = ...           # line 388

    async def get_vector_context(...) -> Tuple[str, Dict[str, Any]]: ...   # line 1587
    async def _build_vector_context(...) -> Tuple[str, Dict[str, Any]]: ...  # line 2239
```

```python
# parrot/stores/abstract.py
class AbstractStore(ABC):
    @abstractmethod
    async def similarity_search(self, ...) -> list: ...             # line 162
    @abstractmethod
    async def from_documents(self, documents, collection=None, **kwargs) -> Callable: ...  # line 175
    @abstractmethod
    async def add_documents(self, documents, collection=None, **kwargs) -> None: ...  # line 207
```

```python
# parrot/stores/utils/chunking.py
@dataclass
class ChunkInfo:                                        # line 8
    chunk_id: str
    parent_document_id: str
    chunk_index: int
    chunk_text: str
    start_position: int
    end_position: int
    chunk_embedding: np.ndarray
    metadata: Dict[str, Any]

class LateChunkingProcessor:                            # line 20
    def __init__(self, vector_store, chunk_size=8192,
                 chunk_overlap=200, preserve_sentences=True,
                 min_chunk_size=100): ...

    async def process_document_late_chunking(           # line 42
        self, document_text: str, document_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Tuple[np.ndarray, List[ChunkInfo]]: ...
```

```python
# parrot/loaders/abstract.py
async def _chunk_with_late_chunking(                    # line 1143
    self, documents: List[Document], vector_store=None,
    store_full_document: bool = True,
) -> List[Document]: ...
# parent assembly at line 1190: 'is_full_document': True, 'document_type': 'parent'
# child assembly at line 1130: 'parent_document_id': doc.metadata.get('document_id', ...)
```

```python
# parrot/stores/postgres.py
async def add_documents(...) -> None: ...               # line 586
# from_documents at line 2551, store_full_document path at line 2629-2635:
#     'is_full_document': True, 'document_type': 'parent'
# parent filter at line 2724:
#     doc_filters = {'is_full_document': True}
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `AbstractParentSearcher` | `AbstractBot.parent_searcher` attribute | optional kwarg | new attribute |
| `InTableParentSearcher.fetch()` | `AbstractStore` connection | SQL `SELECT WHERE document_id IN (:ids)` | depends on store; postgres has this pattern at line 2724 |
| Bot expansion logic | `metadata['parent_document_id']` | dict read | `parrot/loaders/abstract.py:1130`, `parrot/stores/utils/chunking.py:11,83` |
| Bot expansion logic | FEAT-126 reranker output | `list[RerankedDocument]` consumed before expansion | composition order documented |
| `similarity_search` filter | `metadata['is_chunk']` / `is_full_document` | WHERE clause on metadata JSON column | postgres existing pattern at line 2724 |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot/stores/parents/`~~ — created by this feature.
- ~~`AbstractParentSearcher`, `InTableParentSearcher`~~ — none exist.
- ~~`AbstractBot.parent_searcher`, `AbstractBot.expand_to_parent`~~ — new
  attributes.
- ~~A separate `parent_documents` table~~ — explicitly rejected; we use
  in-table storage.
- ~~`Document.parent`, `SearchResult.parent`~~ — no top-level fields;
  parents are linked via `metadata['parent_document_id']` only.
- ~~`document_type='parent_chunk'`~~ — does not yet exist; this feature
  introduces it as a new value alongside the existing `'parent'`.
- ~~`is_chunk` as a universal marker~~ — `chunking.py:89` sets it for
  late-chunking only. This feature makes it universal across loaders.
- ~~A `RerankerRegistry` integration with parent searchers~~ — registries
  are out of scope; constructor injection is the only configuration path.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Mirror the `AbstractClient` / `AbstractStore` async-first pattern for
  `AbstractParentSearcher` — one required `async` method, optional health
  check.
- The expansion loop in `_build_vector_context` must preserve ordering:
  iterate `search_results` once, accumulate `parent_id → best_score` and
  the order of first occurrence of each parent. Final order is "first-seen"
  order, which under sorted children is "best-score-first".
- `InTableParentSearcher` issues exactly **one** SQL round trip per
  `fetch()` call (`document_id IN (:ids)`), regardless of how many parents
  are requested. No N+1.
- When the FEAT-126 reranker is configured, expansion happens **after** the
  reranker, on the reranker's already-truncated top-K. We do NOT expand
  to parents and then rerank parents — that would defeat the precision
  benefit of child-level scoring.
- Marking `is_chunk: True` at insertion time is idempotent: if a Document
  already has it, do not overwrite.
- The 3-level path keeps the original document's `document_id` for
  parent_chunks via `parent_chunk.metadata['source_document_id'] =
  doc.document_id`. This is for telemetry/audit; retrieval does not use it.

### Known Risks / Gotchas

1. **Token explosion when expanding to parents.** A query that hits 10
   children spread across 10 distinct parents produces 10 parent payloads
   in the LLM context. With 4k-token parent_chunks, that is 40k tokens —
   already heavy on Sonnet/Opus prompts. Mitigation:
   `context_search_limit=10` is already conservative; recommend lowering it
   to 5 when `expand_to_parent=True` and document this in §7. Acceptance
   criterion does not enforce this — calibration depends on the corpus.
2. **Cold-start re-embedding required.** Collections ingested before this
   feature do not have universal `is_chunk: True` markers. The default
   filter excludes parents using a `is_chunk=True OR is_full_document IS
   NULL` predicate to cover legacy data, but operators should be advised
   to re-ingest where possible.
3. **`document_type='parent_chunk'` collision** with any existing
   convention. We checked — `document_type` is only ever set to `'parent'`
   in `parrot/stores/postgres.py:2635` and `parrot/loaders/abstract.py:1196`.
   No collision.
4. **Composition with FEAT-126 reranker over-fetch.** FEAT-126 over-fetches
   `limit * 4` candidates before reranking. After reranking, top
   `context_search_limit` are kept. Parent expansion then runs on those.
   If the same parent has 4 children all scored highly by the reranker,
   the dedupe collapses them to 1 parent — which means we end up sending
   *fewer* parents than `context_search_limit`. This is correct behaviour
   and should be documented, not "fixed".
5. **In-table parent rows polluting MMR diversity.** Even with the default
   `is_chunk=True` filter, MMR's similarity computation could hit parent
   embeddings during the diversification step if the store does not push
   the filter into the SQL query (filtering post-hoc is too late). Verify
   that postgres `mmr_search` applies the filter to the candidate set, not
   the result set.
6. **Backward compatibility of similarity_search.** Some callers (e.g.,
   internal tooling, scripts) may rely on parents appearing in
   `similarity_search` output. The `include_parents=True` escape hatch is
   their migration path. Document this in the release notes.
7. **Searcher composability for non-postgres stores.** `InTableParentSearcher`
   targets postgres metadata JSON queries. Milvus/Faiss/Bigquery may need
   their own implementations or filter syntax. v1 ships postgres only;
   other stores either extend the in-table impl or implement a dedicated
   `<Store>ParentSearcher`. Document the gap.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| (none) | — | No new dependencies. Stdlib + existing pgvector + pydantic. |

---

## 8. Open Questions

- [ ] Default `parent_chunk_threshold_tokens` (currently 8000): is 8000 the
      right knee, or should we go higher (16000) given modern long-context
      models? Benchmark on real handbooks before finalising. — *Owner: Jesus Lara*
- [ ] When `expand_to_parent=True` and the parent payload pushes the prompt
      over the LLM's max input, do we (a) silently truncate the parent,
      (b) drop the lowest-scored parent, or (c) raise to the caller?
      Recommendation: (b), with a WARNING log. — *Owner: implementation, decide
      after first integration test reveals real numbers.*
- [ ] Should `expand_to_parent` be exposable in `chatbot.yaml` / DB-driven
      bot config (the `_from_db` path in `parrot/bots/chatbot.py:387`)?
      Currently constructor-only. — *Owner: Jesus Lara*
- [ ] `ParentSearcher` selection in DB-driven config: by name (`"in_table"`
      → registry) or by import path string? Future work; out of scope for
      v1 but the answer informs whether we ship a registry now. — *Owner:
      Jesus Lara*
- [ ] List of stores that need their own `<Store>ParentSearcher` impl in v2
      (milvus, faiss, bigquery, arango). v1 = postgres only. — *Owner:
      implementation*

---

## Worktree Strategy

**Default isolation unit: `per-spec` (sequential tasks).**

Tasks form a dependency chain:

1. `ParentSearcher` interface + InTable impl (Module 1) →
2. Marker standardisation in stores (Module 2) →
3. 3-level hierarchy in late chunking (Module 3) →
4. Bot wiring (Module 4) →
5. Tests (Module 5) →
6. Docs (Module 6).

Module 3 can in principle parallelise with Module 4, but they touch related
files and the integration test in Module 5 needs both. Sequential is
simpler.

```bash
git worktree add -b feat-128-parent-child-retrieval \
  .claude/worktrees/feat-128-parent-child-retrieval HEAD
```

**Cross-feature dependencies**:

- **Soft compose** with **FEAT-126** (cross-encoder reranker). If FEAT-126
  is merged first, this spec wires expansion *after* the reranker. If this
  spec lands first, the reranker integrates cleanly later. Either order
  works; integration tests covering the combined flow should land in
  whichever spec ships second.
- **Soft compose** with `ai-parrot-loaders-metadata-standarization` and
  **FEAT-127** (contextual headers). No conflict; the metadata fields they
  touch are disjoint from the parent-child markers used here.
- **No hard blockers**.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-27 | Jesus Lara | Initial draft from in-conversation design. |
