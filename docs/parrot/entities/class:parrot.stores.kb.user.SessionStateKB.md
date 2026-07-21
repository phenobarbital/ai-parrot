---
type: Wiki Entity
title: SessionStateKB
id: class:parrot.stores.kb.user.SessionStateKB
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: KB that retrieves from session state.
relates_to:
- concept: class:parrot.stores.kb.abstract.AbstractKnowledgeBase
  rel: extends
---

# SessionStateKB

Defined in [`parrot.stores.kb.user`](../summaries/mod:parrot.stores.kb.user.md).

```python
class SessionStateKB(AbstractKnowledgeBase)
```

KB that retrieves from session state.

## Methods

- `async def search(self, query: str, ctx: RequestContext=None, **kwargs) -> List[Dict]` — Extract relevant session state.
