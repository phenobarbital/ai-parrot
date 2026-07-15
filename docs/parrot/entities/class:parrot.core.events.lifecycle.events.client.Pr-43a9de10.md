---
type: Wiki Entity
title: PromptCacheAppliedEvent
id: class:parrot.core.events.lifecycle.events.client.PromptCacheAppliedEvent
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Emitted when prompt caching is applied to an LLM call.
relates_to:
- concept: class:parrot.core.events.lifecycle.base.LifecycleEvent
  rel: extends
---

# PromptCacheAppliedEvent

Defined in [`parrot.core.events.lifecycle.events.client`](../summaries/mod:parrot.core.events.lifecycle.events.client.md).

```python
class PromptCacheAppliedEvent(LifecycleEvent)
```

Emitted when prompt caching is applied to an LLM call.

FEAT-181 — Provider-Agnostic Prompt Caching.

Attributes:
    client_name: Provider identifier (``"anthropic"``, ``"openai"``, etc.).
    model: Model name/identifier being called.
    blocks_marked: Number of ``cache_control`` blocks applied to the
        system prompt. For Anthropic: number of cacheable blocks (≤4).
        For OpenAI/Gemini: 0 (caching is implicit or resource-based).
    est_tokens: Estimated cacheable token count (rough 4-chars-per-token
        estimate). Used for observability only.
    segment_hashes: SHA-256 hashes of each cacheable segment text.
        NEVER the raw segment content — privacy-safe.
        Uses ``tuple`` for immutability; ``to_dict()`` converts to list.
