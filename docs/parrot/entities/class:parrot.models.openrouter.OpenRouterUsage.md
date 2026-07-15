---
type: Wiki Entity
title: OpenRouterUsage
id: class:parrot.models.openrouter.OpenRouterUsage
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Cost and usage information from OpenRouter generation responses.
---

# OpenRouterUsage

Defined in [`parrot.models.openrouter`](../summaries/mod:parrot.models.openrouter.md).

```python
class OpenRouterUsage(BaseModel)
```

Cost and usage information from OpenRouter generation responses.

Populated from OpenRouter's generation stats endpoint
(GET /api/v1/generation?id={generation_id}).

Attributes:
    generation_id: Unique identifier for the generation.
    model: Model used for the generation.
    total_cost: Total cost in USD for the generation.
    prompt_tokens: Number of prompt tokens used.
    completion_tokens: Number of completion tokens generated.
    native_tokens_prompt: Native token count for prompt (provider-specific).
    native_tokens_completion: Native token count for completion (provider-specific).
    provider_name: Name of the upstream provider that served the request.
