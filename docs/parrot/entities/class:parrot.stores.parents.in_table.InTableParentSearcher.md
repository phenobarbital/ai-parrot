---
type: Wiki Entity
title: InTableParentSearcher
id: class:parrot.stores.parents.in_table.InTableParentSearcher
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Fetch parents from the same vector table by metadata filter.
relates_to:
- concept: class:parrot.stores.parents.abstract.AbstractParentSearcher
  rel: extends
---

# InTableParentSearcher

Defined in [`parrot.stores.parents.in_table`](../summaries/mod:parrot.stores.parents.in_table.md).

```python
class InTableParentSearcher(AbstractParentSearcher)
```

Fetch parents from the same vector table by metadata filter.

Default implementation for postgres / pgvector.  Issues a single SQL
query per :meth:`fetch` call regardless of how many parent IDs are
requested — no N+1.

**Implementation**: Approach A (direct connection access).  Uses the
store's ``session()`` async context manager to issue a raw parameterised
SELECT.  The parent filter covers both legacy ``is_full_document=True``
parents and the new ``document_type='parent_chunk'`` intermediate
parents introduced by FEAT-128.

Args:
    store: An :class:`~parrot.stores.abstract.AbstractStore` instance.
        The store MUST expose a ``session()`` async context manager
        (as implemented by :class:`~parrot.stores.postgres.PgVectorStore`).

## Methods

- `async def fetch(self, parent_ids: List[str]) -> Dict[str, Document]` — Fetch parent documents by ID in a single SQL round trip.
