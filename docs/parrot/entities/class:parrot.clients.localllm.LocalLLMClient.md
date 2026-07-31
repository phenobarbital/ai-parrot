---
type: Wiki Entity
title: LocalLLMClient
id: class:parrot.clients.localllm.LocalLLMClient
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Client for local/self-hosted OpenAI-compatible LLM servers.
relates_to:
- concept: class:parrot.clients.gpt.OpenAIClient
  rel: extends
---

# LocalLLMClient

Defined in [`parrot.clients.localllm`](../summaries/mod:parrot.clients.localllm.md).

```python
class LocalLLMClient(OpenAIClient)
```

Client for local/self-hosted OpenAI-compatible LLM servers.

Extends OpenAIClient with local-server-friendly defaults:
- No API key required (optional)
- Configurable base_url (defaults to vLLM's ``http://localhost:8000/v1``)
- Higher timeout (120s vs 60s for cloud)
- Responses API disabled (local servers don't support it)
- Relaxed structured output model guard

Supports Ollama, vLLM, llama.cpp, LM Studio, and any server that
exposes an OpenAI-compatible ``/v1`` API.

Args:
    api_key: Optional API key. Defaults to None (most local servers
        don't require authentication). Falls back to
        ``LOCAL_LLM_API_KEY`` env var.
    base_url: Base URL of the local server. Defaults to
        ``http://localhost:8000/v1``. Falls back to
        ``LOCAL_LLM_BASE_URL`` env var.
    model: Default model to use. Falls back to ``LOCAL_LLM_MODEL``
        env var, then ``llama3.1:8b``.
    **kwargs: Additional arguments passed to OpenAIClient.

Example:
    >>> client = LocalLLMClient()
    >>> response = await client.ask("Hello!")

    >>> # Point to Ollama
    >>> client = LocalLLMClient(
    ...     base_url="http://localhost:11434/v1",
    ...     model="llama3.1:8b"
    ... )

## Methods

- `async def get_client(self) -> 'AsyncOpenAI'` — Initialize AsyncOpenAI with local server URL.
- `async def ask(self, prompt: str, model: Union[str, LocalLLMModel]=None, **kwargs)` — Ask the local LLM a question.
- `async def ask_stream(self, prompt: str, model: Union[str, LocalLLMModel]=None, **kwargs)` — Stream the local LLM's response.
- `async def list_models(self) -> List[str]` — List models available on the local server.
- `async def health_check(self) -> bool` — Check if the local server is reachable.
- `async def invoke(self, prompt: str, *, output_type: Optional[type]=None, structured_output: Optional[StructuredOutputConfig]=None, model: Optional[str]=None, system_prompt: Optional[str]=None, max_tokens: int=4096, temperature: float=0.0, use_tools: bool=False, tools: Optional[list]=None) -> InvokeResult` — Lightweight stateless invocation for LocalLLMClient.
