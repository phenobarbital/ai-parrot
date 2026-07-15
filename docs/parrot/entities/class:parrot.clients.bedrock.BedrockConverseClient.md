---
type: Wiki Entity
title: BedrockConverseClient
id: class:parrot.clients.bedrock.BedrockConverseClient
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Client for AWS Bedrock's native Converse API.
relates_to:
- concept: class:parrot.clients.base.AbstractClient
  rel: extends
---

# BedrockConverseClient

Defined in [`parrot.clients.bedrock`](../summaries/mod:parrot.clients.bedrock.md).

```python
class BedrockConverseClient(AbstractClient)
```

Client for AWS Bedrock's native Converse API.

Uses ``aioboto3`` to call ``bedrock-runtime`` directly, supporting any
Bedrock-hosted model family (Claude, Nova, Llama, Mistral, ...) — not
just Claude, which is all :class:`~parrot.clients.claude.AnthropicClient`
(``backend="bedrock"``) exposes.

## Methods

- `async def get_client(self) -> Any` — Create and return an aioboto3 Bedrock Runtime client.
- `async def apply_guardrail_text(self, text: str, source: str='OUTPUT') -> str` — Apply the configured Bedrock guardrail to standalone text.
- `async def ask(self, prompt: str, model: Optional[str]=None, max_tokens: Optional[int]=None, temperature: Optional[float]=None, files: Optional[List[Union[str, Path]]]=None, system_prompt: Optional[str]=None, structured_output: Union[type, StructuredOutputConfig, None]=None, user_id: Optional[str]=None, session_id: Optional[str]=None, tools: Optional[List[Dict[str, Any]]]=None, use_tools: Optional[bool]=None, deep_research: bool=False, background: bool=False, lazy_loading: bool=False, thinking_budget: Optional[int]=None, output_schema: Optional[Dict[str, Any]]=None, prompt_cache: bool=False, guardrail_id: Optional[str]=None, guardrail_version: Optional[str]=None) -> AIMessage` — Ask Bedrock a question via the Converse API, with tool-use loop.
- `async def ask_stream(self, prompt: str, model: Optional[str]=None, max_tokens: Optional[int]=None, temperature: Optional[float]=None, files: Optional[List[Union[str, Path]]]=None, system_prompt: Optional[str]=None, user_id: Optional[str]=None, session_id: Optional[str]=None, tools: Optional[List[Dict[str, Any]]]=None, deep_research: bool=False, agent_config: Optional[Dict[str, Any]]=None, lazy_loading: bool=False, thinking_budget: Optional[int]=None, guardrail_id: Optional[str]=None, guardrail_version: Optional[str]=None) -> AsyncIterator[Union[str, AIMessage]]` — Stream a Bedrock Converse response.
- `async def resume(self, session_id: str, user_input: str, state: Dict[str, Any]) -> AIMessage` — Resume a suspended Bedrock tool-use execution.
- `async def invoke(self, prompt: str, *, output_type: Optional[type]=None, structured_output: Optional[StructuredOutputConfig]=None, model: Optional[str]=None, system_prompt: Optional[str]=None, max_tokens: int=4096, temperature: float=0.0, use_tools: bool=False, tools: Optional[list]=None) -> InvokeResult` — Lightweight stateless invocation for BedrockConverseClient.
