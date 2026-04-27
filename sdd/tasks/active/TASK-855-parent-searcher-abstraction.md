# TASK-855: ParentSearcher abstraction + InTable default impl

**Feature**: FEAT-128 — Parent-Child Retrieval with Composable Parent Searcher
**Spec**: `sdd/specs/parent-child-retrieval.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Module 1 of FEAT-128. Introduce the composable `ParentSearcher` abstraction
that decouples *where* parent payloads live from *how* the bot retrieves
them. The default implementation `InTableParentSearcher` issues a single
SQL round trip against the same vector table the chunks live in, filtered
to parent rows.

This task lays the foundation that TASK-858 (bot wiring) will consume.
It is independent from TASK-856 (marker standardisation) at the code level
but logically pairs with it: the InTable searcher relies on the parent
markers (`is_full_document=True` and `document_type='parent_chunk'`) being
populated by ingestion code that already exists today.

Reference: spec §2 (Architectural Design), §3 (Module 1).

---

## Scope

- Create the new package `packages/ai-parrot/src/parrot/stores/parents/`
  with `__init__.py`, `abstract.py`, `in_table.py`.
- Implement `AbstractParentSearcher` (ABC) with one required `async`
  method `fetch(parent_ids: list[str]) -> dict[str, Document]` and an
  optional `health_check() -> bool` default-True.
- Implement `InTableParentSearcher(store: AbstractStore)` with a
  single-SQL-round-trip implementation. Uses
  `store.similarity_search(...)` is **NOT acceptable** — that is for
  vector neighbourhood queries. The searcher MUST issue a direct
  `SELECT ... WHERE document_id IN (:ids) AND (is_full_document = true
  OR document_type = 'parent_chunk')` against the underlying connection.
- Export both classes from
  `parrot.stores.parents.__init__`.
- Write unit tests covering: ABC enforcement, fetch hits, fetch misses
  (missing IDs absent without exception), filter excludes chunk rows.

**NOT in scope**:
- Bot-side wiring (TASK-858).
- Default-filter changes to `similarity_search` (TASK-856).
- Any non-postgres store implementation (out of scope per spec §1).
- Registry / DB-driven selection (deferred per spec §8).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/stores/parents/__init__.py` | CREATE | Package exports: `AbstractParentSearcher`, `InTableParentSearcher`. |
| `packages/ai-parrot/src/parrot/stores/parents/abstract.py` | CREATE | ABC with `fetch` + `health_check`. |
| `packages/ai-parrot/src/parrot/stores/parents/in_table.py` | CREATE | Default postgres-backed impl. |
| `packages/ai-parrot/tests/stores/parents/__init__.py` | CREATE | Test package marker. |
| `packages/ai-parrot/tests/stores/parents/test_abstract.py` | CREATE | ABC enforcement tests. |
| `packages/ai-parrot/tests/stores/parents/test_in_table.py` | CREATE | InTable unit tests (mocked store). |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Verified against the codebase on 2026-04-27. Use these
> exact imports and signatures. If anything has drifted, re-verify with
> `grep`/`read` before coding.

### Verified Imports

```python
from abc import ABC, abstractmethod
from parrot.stores.abstract import AbstractStore   # parrot/stores/abstract.py:17
from parrot.stores.models import Document           # parrot/stores/models.py:21
```

### Existing Signatures to Use

```python
# parrot/stores/abstract.py
class AbstractStore(ABC):
    """Base class for all vector stores. Async context-manager pattern."""

    @abstractmethod
    async def similarity_search(self, query: str, collection=None,
                                limit: int = 2, similarity_threshold: float = 0.0,
                                search_strategy: str = "auto",
                                metadata_filters: Optional[dict] = None,
                                **kwargs) -> list: ...   # line 162

    # Concrete stores expose a connection pool / engine. Postgres uses
    # `self._connection` plus asyncpg in `parrot/stores/postgres.py`.
```

```python
# parrot/stores/models.py:21
class Document(BaseModel):
    page_content: str
    metadata: Dict[str, Any]
    # other fields irrelevant to this task
```

```python
# parrot/stores/postgres.py — pattern for direct SQL on the metadata JSON column
# Existing example showing the metadata filter pattern (line 2724):
#     doc_filters = {'is_full_document': True}
#     doc_results = await self.similarity_search(..., metadata_filters=doc_filters, ...)
# Use this same JSON-column filter style; do NOT invent new SQL clauses.
```

### Does NOT Exist

- ~~`parrot.stores.parents`~~ — created by THIS task.
- ~~`AbstractStore.fetch_by_ids`~~ — no such method. Use the store's
  underlying connection (postgres: asyncpg) or compose via
  `metadata_filters` on existing methods.
- ~~`Document.parent`, `SearchResult.parent`~~ — parents are ONLY linked
  via `metadata['parent_document_id']`. Do not invent attributes.
- ~~`document_type='parent_chunk'`~~ — does not yet exist in the codebase
  but the searcher MUST treat it as a valid parent marker (TASK-857
  introduces the value at ingestion).
- ~~A `parent_documents` table~~ — explicitly rejected. In-table only.

---

## Implementation Notes

### Pattern to Follow

Mirror the `AbstractClient` async-first pattern: one required `async`
method, optional health check.

```python
# parrot/stores/parents/abstract.py
from abc import ABC, abstractmethod
from typing import Dict, List
from parrot.stores.models import Document


class AbstractParentSearcher(ABC):
    """Composable strategy for fetching parent documents by ID.

    Implementations MUST:
    - Return a dict keyed by parent_document_id.
    - Silently omit IDs that cannot be found (data gaps are normal).
    - Raise only on infrastructure failures (connection lost, etc.).
    """

    @abstractmethod
    async def fetch(self, parent_ids: List[str]) -> Dict[str, Document]: ...

    async def health_check(self) -> bool:
        return True
```

### InTableParentSearcher — single-round-trip SQL

The implementation MUST issue exactly ONE SQL query per `fetch()` call
regardless of `len(parent_ids)`. No N+1.

The store-agnostic API needed is `document_id IN (:ids)` plus a metadata
filter `is_full_document=True OR document_type='parent_chunk'`.

For the postgres store specifically, the pattern at
`parrot/stores/postgres.py:2724` (`doc_filters = {'is_full_document':
True}` passed via `metadata_filters` to `similarity_search`) does NOT
match our needs because:
1. Similarity search requires a `query` string and runs vector ranking.
2. We need an OR across two metadata predicates, not a single key match.

**Two acceptable approaches** — pick whichever is cleaner and document the
choice in the docstring:

**Approach A — direct connection access** (preferred for v1):
Use the store's underlying asyncpg pool. Inspect `parrot/stores/postgres.py`
for the connection-acquisition pattern (look for `await self.acquire()`
or similar) and issue a parameterised SELECT.

**Approach B — composite metadata filter helper**:
Add a non-vector helper to `AbstractStore` (e.g.,
`get_documents_by_ids(ids, metadata_filters)`) that returns rows by ID
without running similarity. Only do this if Approach A would require
duplicating connection-management code. If you go this route, also
implement the postgres concrete method.

Whichever path is taken, the resulting SQL semantics MUST be:

```sql
SELECT document_id, content, metadata
FROM <collection_table>
WHERE document_id = ANY(:ids)
  AND ((metadata->>'is_full_document')::boolean = true
       OR metadata->>'document_type' = 'parent_chunk')
```

Map results to `Document(page_content=..., metadata=...)` and return them
keyed by `document_id`.

### Key Constraints

- Async throughout — no blocking I/O.
- `self.logger = logging.getLogger(__name__)` in the in-table impl.
- DEBUG log a single line per `fetch()` summarising
  `requested=N, found=M`. Useful for the bot's fall-through path.
- Pure stdlib + existing project deps. No new packages.
- Do NOT raise on individual misses — that is the bot's responsibility
  to handle (TASK-858).

### References in Codebase

- `parrot/stores/postgres.py:2629-2635` — the parent insertion path that
  sets `is_full_document: True, document_type: 'parent'`.
- `parrot/stores/postgres.py:2724` — existing precedent for filtering
  parents by `is_full_document`.
- `parrot/stores/utils/chunking.py:83-89` — the child-chunk path that
  sets `parent_document_id` and `is_chunk: True`.

---

## Acceptance Criteria

- [ ] `parrot.stores.parents` package importable:
      `from parrot.stores.parents import AbstractParentSearcher, InTableParentSearcher`
- [ ] `AbstractParentSearcher` cannot be instantiated directly.
- [ ] `InTableParentSearcher.fetch([])` returns `{}` without DB hit.
- [ ] `InTableParentSearcher.fetch(['known_id'])` returns the parent
      Document keyed by `'known_id'`.
- [ ] `InTableParentSearcher.fetch(['missing_id'])` returns `{}`, no
      exception.
- [ ] Mixed input (one chunk-id, one parent-id) returns ONLY the parent;
      chunk rows are filtered out by the `is_full_document OR
      document_type='parent_chunk'` predicate.
- [ ] Exactly one SQL round trip per `fetch()` call (verified via mock /
      explain log).
- [ ] All unit tests pass: `pytest packages/ai-parrot/tests/stores/parents/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/stores/parents/`

---

## Test Specification

```python
# packages/ai-parrot/tests/stores/parents/test_abstract.py
import pytest
from parrot.stores.parents import AbstractParentSearcher


class TestAbstractParentSearcher:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            AbstractParentSearcher()

    def test_subclass_must_implement_fetch(self):
        class Incomplete(AbstractParentSearcher):
            pass
        with pytest.raises(TypeError):
            Incomplete()

    async def test_default_health_check_returns_true(self):
        class Minimal(AbstractParentSearcher):
            async def fetch(self, parent_ids):
                return {}
        assert await Minimal().health_check() is True
```

```python
# packages/ai-parrot/tests/stores/parents/test_in_table.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.stores.parents import InTableParentSearcher
from parrot.stores.models import Document


@pytest.fixture
def mock_store():
    """Mock AbstractStore exposing whatever connection accessor the
    in_table impl uses. Adjust to match the chosen implementation
    approach (A — direct connection, or B — helper method)."""
    store = MagicMock()
    return store


class TestInTableParentSearcher:
    async def test_empty_input_returns_empty(self, mock_store):
        searcher = InTableParentSearcher(store=mock_store)
        result = await searcher.fetch([])
        assert result == {}

    async def test_fetches_existing_parents_keyed_by_id(self, mock_store):
        # Arrange: store returns two parent rows
        # Act: searcher.fetch(['p1', 'p2'])
        # Assert: result == {'p1': Document(...), 'p2': Document(...)}
        ...

    async def test_silently_skips_missing_ids(self, mock_store):
        # Arrange: store returns only 'p1'
        # Act: searcher.fetch(['p1', 'missing'])
        # Assert: result == {'p1': Document(...)} ; no exception
        ...

    async def test_chunk_ids_are_filtered_out_by_marker_predicate(self, mock_store):
        """A row whose metadata is is_chunk=True (not is_full_document and
        not document_type=parent_chunk) MUST NOT appear in the result even
        if its document_id was in the input list."""
        ...

    async def test_single_round_trip(self, mock_store):
        """Verify exactly one DB call regardless of input size."""
        ...

    async def test_health_check_returns_true(self, mock_store):
        searcher = InTableParentSearcher(store=mock_store)
        assert await searcher.health_check() is True
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/parent-child-retrieval.spec.md` — focus
   on §2 (Architectural Design) and §3 (Module 1).
2. **Verify the Codebase Contract** — confirm
   `parrot.stores.abstract.AbstractStore` and
   `parrot.stores.models.Document` still exist with the listed shapes.
3. **Pick implementation approach** (A vs B above) and document the
   choice in the `InTableParentSearcher` class docstring.
4. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`.
5. **Implement** the package, then the tests.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
