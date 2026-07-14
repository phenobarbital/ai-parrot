---
type: Wiki Entity
title: AbstractKnowledgeBase
id: class:parrot.stores.kb.abstract.AbstractKnowledgeBase
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Base class for all knowledge bases.
---

# AbstractKnowledgeBase

Defined in [`parrot.stores.kb.abstract`](../summaries/mod:parrot.stores.kb.abstract.md).

```python
class AbstractKnowledgeBase(ABC)
```

Base class for all knowledge bases.

## Methods

- `async def should_activate(self, query: str, context: Dict[str, Any]) -> Tuple[bool, float]` — Determine if this KB should be activated for the query.
- `async def close(self)` — Cleanup resources if needed.
- `async def search(self, query: str, k: int=5, score_threshold: float=0.6, user_id: str=None, session_id: str=None, ctx: RequestContext=None, **kwargs) -> List[Dict[str, Any]]` — Search for relevant facts/information.
- `def format_context(self, results: List[Dict]) -> str` — Format results for prompt injection.
