---
type: Wiki Entity
title: CompletionUsage
id: class:parrot.models.basic.CompletionUsage
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Unified completion usage tracking across different LLM providers.
---

# CompletionUsage

Defined in [`parrot.models.basic`](../summaries/mod:parrot.models.basic.md).

```python
class CompletionUsage(BaseModel)
```

Unified completion usage tracking across different LLM providers.

Speaks both token vocabularies. The canonical fields keep the OpenAI naming
(``prompt_tokens`` / ``completion_tokens``), but the model also accepts and
emits the OTel-GenAI / Anthropic naming (``input_tokens`` / ``output_tokens``)
so it interoperates with any framework regardless of which dialect it uses:

- **Construction** accepts either name (``CompletionUsage(input_tokens=17)``
  or ``CompletionUsage(prompt_tokens=17)``) via field ``validation_alias``.
- **Read access** exposes both (``usage.input_tokens`` and
  ``usage.prompt_tokens``).
- **Serialization** (``model_dump`` / ``model_dump_json``) includes both
  vocabularies via computed fields.

## Methods

- `def input_tokens(self) -> int` — Alias for :attr:`prompt_tokens` (OTel GenAI ``input_tokens``).
- `def output_tokens(self) -> int` — Alias for :attr:`completion_tokens` (OTel GenAI ``output_tokens``).
- `def from_openai(cls, usage: Any) -> 'CompletionUsage'` — Create from OpenAI usage object.
- `def from_groq(cls, usage: Any) -> 'CompletionUsage'` — Create from Groq usage object.
- `def from_claude(cls, usage: Dict[str, Any]) -> 'CompletionUsage'` — Create from Claude usage dict.
- `def from_bedrock(cls, usage: Dict[str, Any]) -> 'CompletionUsage'` — Create from AWS Bedrock Converse API usage dict.
- `def from_gemini(cls, usage: Dict[str, Any]) -> 'CompletionUsage'` — Create from Gemini/Vertex AI usage dict.
- `def from_claude_agent(cls, result_usage: Optional[Dict[str, Any]]=None, *, total_cost_usd: Optional[float]=None, num_turns: Optional[int]=None, model_usage: Optional[Dict[str, Any]]=None) -> 'CompletionUsage'` — Create from a ``claude_agent_sdk.types.ResultMessage`` payload.
- `def from_grok(cls, usage: Any) -> 'CompletionUsage'` — Create from Grok usage object (dict or xai_sdk protobuf).
