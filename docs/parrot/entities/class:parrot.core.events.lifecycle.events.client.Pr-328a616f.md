---
type: Wiki Entity
title: PromptCacheSkippedEvent
id: class:parrot.core.events.lifecycle.events.client.PromptCacheSkippedEvent
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Emitted when prompt caching is skipped.
relates_to:
- concept: class:parrot.core.events.lifecycle.base.LifecycleEvent
  rel: extends
---

# PromptCacheSkippedEvent

Defined in [`parrot.core.events.lifecycle.events.client`](../summaries/mod:parrot.core.events.lifecycle.events.client.md).

```python
class PromptCacheSkippedEvent(LifecycleEvent)
```

Emitted when prompt caching is skipped.

FEAT-181 — Provider-Agnostic Prompt Caching.

Attributes:
    client_name: Provider identifier.
    model: Model name/identifier.
    reason: Why caching was skipped. One of:

        - ``"below_threshold"`` — cacheable token count < ``_min_cache_tokens``.
        - ``"provider_unsupported"`` — provider does not support caching.
        - ``"feature_off"`` — ``prompt_caching=False`` at the bot level.
        - ``"no_segments"`` — no segments were passed to ``_apply_cache_hints``.
