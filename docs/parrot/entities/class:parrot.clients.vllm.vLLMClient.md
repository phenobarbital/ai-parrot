---
type: Wiki Entity
title: vLLMClient
id: class:parrot.clients.vllm.vLLMClient
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: vLLM client with vLLM-specific features.
relates_to:
- concept: class:parrot.clients.localllm.LocalLLMClient
  rel: extends
---

# vLLMClient

Defined in [`parrot.clients.vllm`](../summaries/mod:parrot.clients.vllm.md).

```python
class vLLMClient(LocalLLMClient)
```

vLLM client with vLLM-specific features.

Extends LocalLLMClient to add:
- Guided output (JSON schema, regex, choices)
- LoRA adapter support per request
- Extended sampling parameters (top_k, min_p, repetition_penalty)
- Health check and server info endpoints
- Batch processing for high throughput

Args:
    base_url: vLLM server URL. Defaults to VLLM_BASE_URL env or
        "http://localhost:8000/v1".
    api_key: Optional API key. Defaults to VLLM_API_KEY env.
    timeout: Request timeout in seconds (default 120).
    **kwargs: Additional arguments passed to LocalLLMClient.

Example:
    >>> client = vLLMClient()
    >>> response = await client.ask("Hello!")

    >>> # With guided JSON output
    >>> schema = {"type": "object", "properties": {"name": {"type": "string"}}}
    >>> response = await client.ask("Extract name", guided_json=schema)

    >>> # With Pydantic structured output
    >>> class Person(BaseModel):
    ...     name: str
    ...     age: int
    >>> response = await client.ask("Extract person", structured_output=Person)

## Methods

- `async def ask(self, prompt: str, model: Optional[Union[str, Enum]]=None, temperature: float=0.7, max_tokens: Optional[int]=None, guided_json: Optional[Dict[str, Any]]=None, guided_regex: Optional[str]=None, guided_choice: Optional[List[str]]=None, guided_grammar: Optional[str]=None, structured_output: Optional[Type[BaseModel]]=None, lora_adapter: Optional[str]=None, top_k: int=-1, min_p: float=0.0, repetition_penalty: float=1.0, length_penalty: float=1.0, **kwargs) -> AIMessage` — Send a prompt to vLLM with optional guided output and LoRA support.
- `async def ask_stream(self, prompt: str, model: Optional[Union[str, Enum]]=None, temperature: float=0.7, max_tokens: Optional[int]=None, guided_json: Optional[Dict[str, Any]]=None, guided_regex: Optional[str]=None, guided_choice: Optional[List[str]]=None, guided_grammar: Optional[str]=None, structured_output: Optional[Type[BaseModel]]=None, lora_adapter: Optional[str]=None, top_k: int=-1, min_p: float=0.0, repetition_penalty: float=1.0, length_penalty: float=1.0, **kwargs) -> AsyncGenerator[str, None]` — Stream response from vLLM with optional guided output and LoRA support.
- `async def health_check(self) -> bool` — Check vLLM server health via /health endpoint.
- `async def server_info(self) -> VLLMServerInfo` — Get vLLM server version and configuration.
- `async def list_models(self) -> List[str]` — List available models on the vLLM server.
- `async def batch_process(self, requests: List[Dict[str, Any]], **kwargs) -> List[AIMessage]` — Process multiple requests concurrently for optimal throughput.
