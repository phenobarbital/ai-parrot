---
type: Wiki Entity
title: Gemma4Client
id: class:parrot.clients.gemma4.Gemma4Client
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Client for Google Gemma 4 multimodal instruction-tuned models.
relates_to:
- concept: class:parrot.clients.base.AbstractClient
  rel: extends
---

# Gemma4Client

Defined in [`parrot.clients.gemma4`](../summaries/mod:parrot.clients.gemma4.md).

```python
class Gemma4Client(AbstractClient)
```

Client for Google Gemma 4 multimodal instruction-tuned models.

Gemma 4 models use AutoProcessor (not AutoTokenizer) and
AutoModelForMultimodalLM (not AutoModelForCausalLM). They support:
  - Text-only and multimodal (image/audio/video) input
  - Optional thinking/chain-of-thought mode via ``enable_thinking``
  - Function calling / tool use via ``tools`` parameter
  - Structured response parsing via ``processor.parse_response()``

## Methods

- `async def get_client(self) -> Any` — Initialize the client context and load the model.
- `async def close(self)` — Clean up resources.
- `async def ask(self, prompt: str, max_tokens: int=512, temperature: float=1.0, files: Optional[List[Union[str, Path]]]=None, system_prompt: Optional[str]=None, user_id: Optional[str]=None, session_id: Optional[str]=None, tools: Optional[List[Dict[str, Any]]]=None, structured_output: Optional[Union[type, StructuredOutputConfig]]=None, **kwargs) -> AIMessage` — Send a prompt and return the response.
- `async def ask_stream(self, prompt: str, model: Optional[str]=None, max_tokens: int=512, temperature: float=1.0, files: Optional[List[Union[str, Path]]]=None, system_prompt: Optional[str]=None, user_id: Optional[str]=None, session_id: Optional[str]=None, tools: Optional[List[Dict[str, Any]]]=None, **kwargs) -> AsyncIterator[Union[str, AIMessage]]` — Pseudo-streaming: generates fully then yields chunks then final AIMessage.
- `async def invoke(self, prompt: str, *, output_type: Optional[type]=None, structured_output: Optional[StructuredOutputConfig]=None, model: Optional[str]=None, system_prompt: Optional[str]=None, max_tokens: int=4096, temperature: float=0.0, use_tools: bool=False, tools: Optional[list]=None) -> InvokeResult` — Lightweight stateless invocation.
- `async def resume(self, session_id: str, user_input: str, state: Dict[str, Any]) -> MessageResponse` — Resume a suspended tool-calling conversation.
- `def get_model_info(self) -> Dict[str, Any]` — Get information about the loaded model.
- `async def clear_model(self)` — Clear model and processor from memory.
