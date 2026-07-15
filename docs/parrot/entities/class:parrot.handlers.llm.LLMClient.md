---
type: Wiki Entity
title: LLMClient
id: class:parrot.handlers.llm.LLMClient
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: LLMClient Handler - Interface for direct LLM interaction.
---

# LLMClient

Defined in [`parrot.handlers.llm`](../summaries/mod:parrot.handlers.llm.md).

```python
class LLMClient(BaseView)
```

LLMClient Handler - Interface for direct LLM interaction.

Endpoints:
    GET /api/v1/ai/clients: List available clients
    GET /api/v1/ai/clients/models: List supported models (optional ?client= filter)
    POST /api/v1/ai/client: Create client and ask (requires 'llm' or 'client' in body)
    POST /api/v1/ai/client/{client_name}: Use specific client and ask

## Methods

- `def post_init(self, *args, **kwargs)`
- `async def get(self)` — GET handler for clients and models.
- `async def post(self)` — POST handler for client interaction.
