---
type: Wiki Entity
title: AnthropicClient
id: class:parrot.clients.claude.AnthropicClient
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Client for interacting with the Anthropic API using the official SDK.
relates_to:
- concept: class:parrot.clients.base.AbstractClient
  rel: extends
---

# AnthropicClient

Defined in [`parrot.clients.claude`](../summaries/mod:parrot.clients.claude.md).

```python
class AnthropicClient(AbstractClient)
```

Client for interacting with the Anthropic API using the official SDK.

## Methods

- `async def get_client(self) -> 'Union[AsyncAnthropic, AsyncAnthropicBedrock, AsyncAnthropicAWS]'` — Build and return the appropriate SDK client for the active backend.
- `async def ask(self, prompt: str, model: Union[Enum, str]=None, max_tokens: Optional[int]=None, temperature: Optional[float]=None, files: Optional[List[Union[str, Path]]]=None, system_prompt: Optional[str]=None, structured_output: Union[type, StructuredOutputConfig, None]=None, user_id: Optional[str]=None, session_id: Optional[str]=None, tools: Optional[List[Dict[str, Any]]]=None, use_tools: Optional[bool]=None, deep_research: bool=False, background: bool=False, lazy_loading: bool=False, context_1m: bool=False) -> AIMessage` — Ask Claude a question with optional conversation memory.
- `async def resume(self, session_id: str, user_input: str, state: Dict[str, Any]) -> AIMessage` — Resume a suspended model execution.
- `async def ask_stream(self, prompt: str, model: Union[ClaudeModel, str]=None, max_tokens: Optional[int]=None, temperature: Optional[float]=None, files: Optional[List[Union[str, Path]]]=None, system_prompt: Optional[str]=None, user_id: Optional[str]=None, session_id: Optional[str]=None, retry_config: Optional[StreamingRetryConfig]=None, on_max_tokens: Optional[str]='retry', tools: Optional[List[Dict[str, Any]]]=None, deep_research: bool=False, agent_config: Optional[Dict[str, Any]]=None, lazy_loading: bool=False, context_1m: bool=False) -> AsyncIterator[Union[str, AIMessage]]` — Stream Claude's response using AsyncIterator with optional conversation memory.
- `async def batch_ask(self, requests: List[BatchRequest], context_1m: bool=False) -> List[AIMessage]` — Process multiple requests in batch.
- `async def ask_to_image(self, prompt: str, image: Union[Path, bytes, Image.Image], reference_images: Optional[List[Union[Path, bytes, Image.Image]]]=None, model: Union[ClaudeModel, str]=ClaudeModel.SONNET_4, max_tokens: Optional[int]=None, temperature: Optional[float]=None, structured_output: Union[type, StructuredOutputConfig]=None, count_objects: bool=False, user_id: Optional[str]=None, session_id: Optional[str]=None, system_prompt: Optional[str]=None, context_1m: bool=False) -> AIMessage` — Ask Claude a question about an image with optional conversation memory.
- `async def summarize_text(self, text: str, max_length: int=500, min_length: int=100, model: Union[ClaudeModel, str]=ClaudeModel.SONNET_4, temperature: Optional[float]=None, user_id: Optional[str]=None, session_id: Optional[str]=None, context_1m: bool=False) -> AIMessage` — Generates a summary for a given text in a stateless manner.
- `async def translate_text(self, text: str, target_lang: str, source_lang: Optional[str]=None, model: Union[ClaudeModel, str]=ClaudeModel.SONNET_4, temperature: Optional[float]=0.2, user_id: Optional[str]=None, session_id: Optional[str]=None, context_1m: bool=False) -> AIMessage` — Translates a given text from a source language to a target language.
- `async def extract_key_points(self, text: str, num_points: int=5, model: Union[ClaudeModel, str]=ClaudeModel.SONNET_4, temperature: Optional[float]=0.3, user_id: Optional[str]=None, session_id: Optional[str]=None, context_1m: bool=False) -> AIMessage` — Extract key points from a given text.
- `async def analyze_sentiment(self, text: str, model: Union[ClaudeModel, str]=ClaudeModel.SONNET_4, temperature: Optional[float]=0.1, user_id: Optional[str]=None, session_id: Optional[str]=None, use_structured: bool=False, context_1m: bool=False) -> AIMessage` — Analyze the sentiment of a given text.
- `async def analyze_product_review(self, review_text: str, product_id: str, product_name: str, model: Union[ClaudeModel, str]=ClaudeModel.SONNET_4, temperature: Optional[float]=0.1, user_id: Optional[str]=None, session_id: Optional[str]=None) -> AIMessage` — Analyze a product review and extract structured information.
- `async def invoke(self, prompt: str, *, output_type: Optional[type]=None, structured_output: Optional[StructuredOutputConfig]=None, model: Optional[str]=None, system_prompt: Optional[str]=None, max_tokens: int=4096, temperature: float=0.0, use_tools: bool=False, tools: Optional[list]=None) -> InvokeResult` — Lightweight stateless invocation for AnthropicClient.
