---
type: Wiki Entity
title: NvidiaClient
id: class:parrot.clients.nvidia.NvidiaClient
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Client for Nvidia NIM's OpenAI-compatible API gateway.
relates_to:
- concept: class:parrot.clients.gpt.OpenAIClient
  rel: extends
---

# NvidiaClient

Defined in [`parrot.clients.nvidia`](../summaries/mod:parrot.clients.nvidia.md).

```python
class NvidiaClient(OpenAIClient)
```

Client for Nvidia NIM's OpenAI-compatible API gateway.

Routes all requests through ``https://integrate.api.nvidia.com/v1`` and
resolves the API key from the constructor argument or the ``NVIDIA_API_KEY``
environment variable (via ``navconfig.config``).

All inherited OpenAI machinery — ``ask``, ``ask_stream``, ``invoke``,
``_chat_completion``, tool calling, structured output, and retry — works
without modification.

The only Nvidia-specific affordance is the ``enable_thinking`` shortcut on
``ask`` / ``ask_stream`` that injects ``chat_template_kwargs`` into
``extra_body`` for reasoning-capable models (e.g. ``z-ai/glm-5.1``).

``enable_thinking`` is propagated to ``_chat_completion`` via an async
context variable so that no changes to the parent's call signatures are
required.

Args:
    api_key: Nvidia NIM API key. Falls back to ``NVIDIA_API_KEY`` env var
        (resolved via ``navconfig.config``).
    **kwargs: Additional arguments passed to ``OpenAIClient`` /
        ``AbstractClient``.

Example::

    client = NvidiaClient(model=NvidiaModel.GLM_5_1)
    response = await client.ask(
        "Explain gradient descent.",
        enable_thinking=True,
    )

## Methods

- `async def ask(self, prompt: str, *, enable_thinking: bool=False, clear_thinking: bool=False, **kwargs) -> AIMessage` — Submit a prompt and return the full response.
- `async def ask_stream(self, prompt: str, *, enable_thinking: bool=False, clear_thinking: bool=False, **kwargs) -> AsyncIterator[str]` — Submit a prompt and stream response chunks.
