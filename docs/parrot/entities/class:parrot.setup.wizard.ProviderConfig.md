---
type: Wiki Entity
title: ProviderConfig
id: class:parrot.setup.wizard.ProviderConfig
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Collected configuration for a single LLM provider.
---

# ProviderConfig

Defined in [`parrot.setup.wizard`](../summaries/mod:parrot.setup.wizard.md).

```python
class ProviderConfig
```

Collected configuration for a single LLM provider.

Attributes:
    provider: Provider key used by LLMFactory (e.g. ``"anthropic"``).
    model: Model identifier (e.g. ``"claude-sonnet-4-6"``).
    env_vars: Environment variable name → value pairs to write to the
        ``.env`` file.
    llm_string: Combined string for LLMFactory in ``"provider:model"``
        format (e.g. ``"anthropic:claude-sonnet-4-6"``).
