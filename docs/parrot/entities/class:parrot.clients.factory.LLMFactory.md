---
type: Wiki Entity
title: LLMFactory
id: class:parrot.clients.factory.LLMFactory
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Factory for creating LLM client instances from string specifications.
---

# LLMFactory

Defined in [`parrot.clients.factory`](../summaries/mod:parrot.clients.factory.md).

```python
class LLMFactory
```

Factory for creating LLM client instances from string specifications.

Supports formats:
- "provider:model" → e.g. "groq:llama-3.3-70b-versatile"
- "provider" → uses default model for provider
- Direct client class or instance

## Methods

- `def parse_llm_string(llm: str) -> Tuple[str, Optional[str]]` — Parse LLM string in format 'provider:model' or 'provider'.
- `def create(llm: str, model_args: Optional[Dict[str, Any]]=None, tool_manager: Optional[Any]=None, **kwargs) -> AbstractClient` — Create an LLM client instance from string specification.
