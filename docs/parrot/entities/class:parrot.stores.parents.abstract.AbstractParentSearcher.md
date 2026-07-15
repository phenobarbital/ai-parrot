---
type: Wiki Entity
title: AbstractParentSearcher
id: class:parrot.stores.parents.abstract.AbstractParentSearcher
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Composable strategy for fetching parent documents by ID.
---

# AbstractParentSearcher

Defined in [`parrot.stores.parents.abstract`](../summaries/mod:parrot.stores.parents.abstract.md).

```python
class AbstractParentSearcher(ABC)
```

Composable strategy for fetching parent documents by ID.

Implementations MUST:
- Return a dict keyed by ``parent_document_id``.
- Silently omit IDs that cannot be found (data gaps are normal).
- Raise only on infrastructure failures (connection lost, etc.).

The bot calls :meth:`fetch` with the deduplicated set of
``parent_document_id`` values extracted from retrieval results, and
uses the returned mapping to substitute parents for children in the
LLM context.

## Methods

- `async def fetch(self, parent_ids: List[str]) -> Dict[str, Document]` — Fetch parent documents by their IDs.
- `async def health_check(self) -> bool` — Optional readiness probe.
