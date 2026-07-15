---
type: Wiki Entity
title: ZaiClient
id: class:parrot.clients.zai.ZaiClient
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Client for Z.ai chat completions using the official ``zai-sdk`` package.
relates_to:
- concept: class:parrot.clients.base.AbstractClient
  rel: extends
---

# ZaiClient

Defined in [`parrot.clients.zai`](../summaries/mod:parrot.clients.zai.md).

```python
class ZaiClient(AbstractClient)
```

Client for Z.ai chat completions using the official ``zai-sdk`` package.

## Methods

- `async def get_client(self) -> Any` — Create the official Z.ai SDK client for the current event loop.
- `async def ask(self, prompt: str, model: Union[str, ZaiModel, None]=None, max_tokens: int=4096, temperature: float=0.7, top_p: float=0.9, files: Optional[List[Union[str, Path]]]=None, system_prompt: Optional[Union[str, list]]=None, structured_output: Union[type, StructuredOutputConfig, None]=None, user_id: Optional[str]=None, session_id: Optional[str]=None, tools: Optional[List[Dict[str, Any]]]=None, use_tools: Optional[bool]=None, thinking: Optional[Union[bool, str, Dict[str, Any]]]=None, deep_thinking: bool=False, **_: Any) -> AIMessage` — Send a non-streaming chat request to Z.ai.
- `async def ask_stream(self, prompt: str, model: Union[str, ZaiModel, None]=None, max_tokens: int=4096, temperature: float=0.7, top_p: float=0.9, files: Optional[List[Union[str, Path]]]=None, system_prompt: Optional[Union[str, list]]=None, user_id: Optional[str]=None, session_id: Optional[str]=None, tools: Optional[List[Dict[str, Any]]]=None, use_tools: Optional[bool]=None, thinking: Optional[Union[bool, str, Dict[str, Any]]]=None, deep_thinking: bool=False, stream_reasoning: bool=False, **_: Any) -> AsyncIterator[Union[str, AIMessage]]` — Stream a Z.ai response, yielding text chunks followed by an
- `async def resume(self, session_id: str, user_input: str, state: Dict[str, Any]) -> AIMessage` — Resume a suspended ZaiClient execution after a HandoffTool / HITL pause.
- `async def invoke(self, prompt: str, *, output_type: Optional[type]=None, structured_output: Optional[StructuredOutputConfig]=None, model: Optional[str]=None, system_prompt: Optional[str]=None, max_tokens: int=4096, temperature: float=0.0, use_tools: bool=False, tools: Optional[list]=None) -> InvokeResult` — Lightweight stateless invocation for ZaiClient.
- `async def embed(self, *args: Any, **kwargs: Any) -> Any` — Embeddings are not implemented by this chat client yet.
