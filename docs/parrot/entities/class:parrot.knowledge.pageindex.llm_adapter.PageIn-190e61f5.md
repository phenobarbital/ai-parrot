---
type: Wiki Entity
title: PageIndexLLMAdapter
id: class:parrot.knowledge.pageindex.llm_adapter.PageIndexLLMAdapter
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Wraps any AbstractClient for PageIndex-compatible LLM calls.
---

# PageIndexLLMAdapter

Defined in [`parrot.knowledge.pageindex.llm_adapter`](../summaries/mod:parrot.knowledge.pageindex.llm_adapter.md).

```python
class PageIndexLLMAdapter
```

Wraps any AbstractClient for PageIndex-compatible LLM calls.

Provides structured output support via Pydantic models and
fallback JSON extraction for providers without native support.

## Methods

- `async def ask(self, prompt: str, structured_output: Union[type, StructuredOutputConfig, None]=None, temperature: float=0.0, system_prompt: Optional[str]=None) -> str` — Send a prompt and return raw text response.
- `async def ask_structured(self, prompt: str, output_type: type, temperature: float=0.0, system_prompt: Optional[str]=None) -> Any` — Send a prompt and return a parsed Pydantic model instance.
- `async def ask_with_finish_info(self, prompt: str, temperature: float=0.0, chat_history: Optional[list[dict[str, str]]]=None, system_prompt: Optional[str]=None) -> tuple[str, str]` — LLM call that returns (text, finish_reason).
- `async def ask_json(self, prompt: str, temperature: float=0.0, system_prompt: Optional[str]=None) -> Any` — Send a prompt and return parsed JSON (dict or list).
