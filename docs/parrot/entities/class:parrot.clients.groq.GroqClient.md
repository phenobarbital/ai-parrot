---
type: Wiki Entity
title: GroqClient
id: class:parrot.clients.groq.GroqClient
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Client for interacting with Groq's API.
relates_to:
- concept: class:parrot.clients.base.AbstractClient
  rel: extends
---

# GroqClient

Defined in [`parrot.clients.groq`](../summaries/mod:parrot.clients.groq.md).

```python
class GroqClient(AbstractClient)
```

Client for interacting with Groq's API.

Note: Groq has a limitation where structured output (JSON mode) cannot be
combined with tool calling in the same request. When both are requested,
this client handles tools first, then makes a separate request for
structured output formatting.

## Methods

- `async def get_client(self) -> 'AsyncGroq'` — Initialize the Groq client.
- `async def ask(self, prompt: str, model: str=GroqModel.LLAMA_3_3_70B_VERSATILE, max_tokens: int=4096, temperature: float=0.1, top_p: float=0.9, files: Optional[List[Union[str, Path]]]=None, system_prompt: Optional[str]=None, structured_output: Union[type, StructuredOutputConfig, None]=None, user_id: Optional[str]=None, session_id: Optional[str]=None, tools: Optional[List[dict]]=None, use_tools: Optional[bool]=None, use_code_interpreter: Optional[bool]=None) -> AIMessage` — Ask Groq a question with optional conversation memory.
- `async def ask_stream(self, prompt: str, model: str=GroqModel.LLAMA_3_3_70B_VERSATILE, max_tokens: int=4096, temperature: float=0.1, top_p: float=0.9, files: Optional[List[Union[str, Path]]]=None, system_prompt: Optional[str]=None, user_id: Optional[str]=None, session_id: Optional[str]=None, tools: Optional[List[dict]]=None, deep_research: bool=False, agent_config: Optional[dict]=None, lazy_loading: bool=False) -> AsyncIterator[Union[str, AIMessage]]` — Stream Groq's response with optional conversation memory.
- `async def resume(self, session_id: str, user_input: str, state: dict) -> AIMessage` — Resume a suspended model execution after HandoffTool pause.
- `async def batch_ask(self, requests)` — Process multiple requests in batch.
- `async def summarize_text(self, text: str, model: str=GroqModel.LLAMA_3_3_70B_VERSATILE, max_tokens: int=1024, temperature: float=0.1, system_prompt: Optional[str]=None, top_p: float=0.9, user_id: Optional[str]=None, session_id: Optional[str]=None) -> AIMessage` — Summarize the given text using Groq API.
- `async def analyze_sentiment(self, text: str, model: Union[GroqModel, str]=GroqModel.KIMI_K2_INSTRUCT, temperature: Optional[float]=0.1, max_tokens: int=1024, top_p: float=0.9, user_id: Optional[str]=None, session_id: Optional[str]=None, use_structured: bool=False) -> AIMessage` — Analyze the sentiment of a given text.
- `async def analyze_product_review(self, review_text: str, product_id: str, product_name: str, model: Union[GroqModel, str]=GroqModel.KIMI_K2_INSTRUCT, temperature: Optional[float]=0.1, max_tokens: int=1024, top_p: float=0.9, user_id: Optional[str]=None, session_id: Optional[str]=None) -> AIMessage` — Analyze a product review and extract structured information.
- `async def invoke(self, prompt: str, *, output_type: Optional[type]=None, structured_output: Optional[StructuredOutputConfig]=None, model: Optional[str]=None, system_prompt: Optional[str]=None, max_tokens: int=4096, temperature: float=0.0, use_tools: bool=False, tools: Optional[list]=None) -> InvokeResult` — Lightweight stateless invocation for GroqClient.
