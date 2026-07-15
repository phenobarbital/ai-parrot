---
type: Wiki Entity
title: AgentKnowledgeHandler
id: class:parrot.handlers.knowledge.AgentKnowledgeHandler
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Manage an agent's PageIndex / GraphIndex documents over REST.
---

# AgentKnowledgeHandler

Defined in [`parrot.handlers.knowledge`](../summaries/mod:parrot.handlers.knowledge.md).

```python
class AgentKnowledgeHandler(BaseView)
```

Manage an agent's PageIndex / GraphIndex documents over REST.

## Methods

- `async def get(self) -> web.StreamResponse` — Dispatch GET to status, ``/search`` (JSON) or ``/ask`` (chunked).
- `async def put(self) -> web.Response` — Upload one or more files into the agent's index.
- `async def post(self) -> web.Response` — Edit existing content in the agent's index.
- `async def delete(self) -> web.Response` — Delete a node (``?node_id=``) or a whole tree from the index.
