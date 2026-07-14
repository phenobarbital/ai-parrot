---
type: Concept
title: handle_a2a_directory()
id: func:parrot.integrations.manager.handle_a2a_directory
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: GET /a2a/directory — returns JSON array of all registered AgentCards.
---

# handle_a2a_directory

```python
async def handle_a2a_directory(request: web.Request) -> web.Response
```

GET /a2a/directory — returns JSON array of all registered AgentCards.

Lists only agents declared with ``kind: a2a`` (including the automatic
A2A companion surface of ``kind: msagent`` bots); other integration
kinds (telegram/slack/etc.) never register into
``app["a2a_discovery_registry"]``.
