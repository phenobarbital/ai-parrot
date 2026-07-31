---
type: Wiki Entity
title: GrokClient
id: class:parrot.clients.grok.GrokClient
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Client for interacting with xAI's Grok models.
relates_to:
- concept: class:parrot.clients.base.AbstractClient
  rel: extends
---

# GrokClient

Defined in [`parrot.clients.grok`](../summaries/mod:parrot.clients.grok.md).

```python
class GrokClient(AbstractClient)
```

Client for interacting with xAI's Grok models.

## Methods

- `async def get_client(self) -> 'AsyncClient'` — Construct and return a fresh xAI AsyncClient for the current loop.
- `async def close(self) -> None` — Close all per-loop SDK clients.
- `async def ask(self, prompt: str, model: str=None, max_tokens: int=16000, temperature: float=0.7, files: Optional[List[Union[str, Path]]]=None, system_prompt: Optional[str]=None, structured_output: Union[type, StructuredOutputConfig, None]=None, user_id: Optional[str]=None, session_id: Optional[str]=None, tools: Optional[List[Dict[str, Any]]]=None, use_tools: Optional[bool]=None) -> MessageResponse` — Send a prompt to Grok and return the response.
- `async def ask_stream(self, prompt: str, model: str=None, max_tokens: int=16000, temperature: float=0.7, files: Optional[List[Union[str, Path]]]=None, system_prompt: Optional[str]=None, structured_output: Union[type, StructuredOutputConfig, None]=None, user_id: Optional[str]=None, session_id: Optional[str]=None, tools: Optional[List[Dict[str, Any]]]=None, deep_research: bool=False, agent_config: Optional[Dict[str, Any]]=None, lazy_loading: bool=False) -> AsyncIterator[Union[str, AIMessage]]` — Stream response from Grok.
- `async def resume(self, session_id: str, user_input: str, state: Dict[str, Any]) -> AIMessage` — Resume a suspended Grok execution after a HandoffTool / HITL pause.
- `async def batch_ask(self, requests: List[Any]) -> List[Any]` — Batch processing not yet implemented for Grok.
- `async def invoke(self, prompt: str, *, output_type: Optional[type]=None, structured_output: Optional[StructuredOutputConfig]=None, model: Optional[str]=None, system_prompt: Optional[str]=None, max_tokens: int=4096, temperature: float=0.0, use_tools: bool=False, tools: Optional[list]=None) -> InvokeResult` — Lightweight stateless invocation for GrokClient.
