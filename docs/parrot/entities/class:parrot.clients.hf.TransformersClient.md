---
type: Wiki Entity
title: TransformersClient
id: class:parrot.clients.hf.TransformersClient
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Client for interacting with HuggingFace transformers micro-LLMs.
relates_to:
- concept: class:parrot.clients.base.AbstractClient
  rel: extends
---

# TransformersClient

Defined in [`parrot.clients.hf`](../summaries/mod:parrot.clients.hf.md).

```python
class TransformersClient(AbstractClient)
```

Client for interacting with HuggingFace transformers micro-LLMs.

This client is designed for small, local models that can run efficiently
on CPU or single GPU setups for quick tasks and lightweight inference.

## Methods

- `async def get_client(self) -> Any` — Initialize the client context and load the model.
- `async def close(self)` — Clean up resources.
- `async def ask(self, prompt: str, max_tokens: int=512, temperature: float=0.7, files: Optional[List[Union[str, Path]]]=None, system_prompt: Optional[str]=None, user_id: Optional[str]=None, session_id: Optional[str]=None, tools: Optional[List[Dict[str, Any]]]=None, structured_output: Optional[Union[type, StructuredOutputConfig]]=None, **kwargs) -> AIMessage` — Send a prompt to the transformer model and return the response.
- `async def ask_stream(self, prompt: str, model: Optional[str]=None, max_tokens: int=512, temperature: float=0.7, files: Optional[List[Union[str, Path]]]=None, system_prompt: Optional[str]=None, user_id: Optional[str]=None, session_id: Optional[str]=None, tools: Optional[List[Dict[str, Any]]]=None, **kwargs) -> AsyncIterator[Union[str, AIMessage]]` — Stream the model's response.
- `async def batch_ask(self, requests: List[Dict[str, Any]]) -> List[AIMessage]` — Process multiple requests in batch.
- `async def invoke(self, prompt: str, *, output_type: Optional[type]=None, structured_output: Optional[StructuredOutputConfig]=None, model: Optional[str]=None, system_prompt: Optional[str]=None, max_tokens: int=4096, temperature: float=0.0, use_tools: bool=False, tools: Optional[list]=None) -> InvokeResult` — Lightweight stateless invocation for TransformersClient.
- `async def resume(self, session_id: str, user_input: str, state: Dict[str, Any]) -> MessageResponse` — Resume is not supported by TransformersClient.
- `def get_model_info(self) -> Dict[str, Any]` — Get information about the loaded model.
- `async def clear_model(self)` — Clear the model from memory.
