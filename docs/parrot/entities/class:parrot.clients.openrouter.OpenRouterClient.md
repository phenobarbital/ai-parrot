---
type: Wiki Entity
title: OpenRouterClient
id: class:parrot.clients.openrouter.OpenRouterClient
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Client for OpenRouter's multi-model API gateway.
relates_to:
- concept: class:parrot.clients.gpt.OpenAIClient
  rel: extends
---

# OpenRouterClient

Defined in [`parrot.clients.openrouter`](../summaries/mod:parrot.clients.openrouter.md).

```python
class OpenRouterClient(OpenAIClient)
```

Client for OpenRouter's multi-model API gateway.

Extends OpenAIClient with OpenRouter-specific features:
- Custom headers (HTTP-Referer, X-Title) for app identification
- Provider routing preferences (fallback, ordering, filtering)
- Cost/usage tracking via generation stats endpoint
- Model listing from OpenRouter's catalog

Args:
    api_key: OpenRouter API key. Falls back to OPENROUTER_API_KEY env var.
    app_name: Application name sent as X-Title header.
    site_url: Site URL sent as HTTP-Referer header.
    provider_preferences: Routing preferences for provider selection.
    **kwargs: Additional arguments passed to OpenAIClient/AbstractClient.

Example:
    >>> client = OpenRouterClient(
    ...     model="deepseek/deepseek-r1",
    ...     provider_preferences=ProviderPreferences(
    ...         order=["DeepInfra", "Together"]
    ...     )
    ... )
    >>> response = await client.ask("Hello!")

## Methods

- `async def get_client(self) -> 'AsyncOpenAI'` — Initialize AsyncOpenAI with OpenRouter base_url and custom headers.
- `async def get_generation_stats(self, generation_id: str) -> OpenRouterUsage` — Fetch cost/usage stats for a specific generation.
- `async def list_models(self) -> List[Dict[str, Any]]` — List all available models from OpenRouter.
