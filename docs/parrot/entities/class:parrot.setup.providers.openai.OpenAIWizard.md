---
type: Wiki Entity
title: OpenAIWizard
id: class:parrot.setup.providers.openai.OpenAIWizard
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Wizard for OpenAI credential collection.
relates_to:
- concept: class:parrot.setup.wizard.BaseClientWizard
  rel: extends
---

# OpenAIWizard

Defined in [`parrot.setup.providers.openai`](../summaries/mod:parrot.setup.providers.openai.md).

```python
class OpenAIWizard(BaseClientWizard)
```

Wizard for OpenAI credential collection.

Collects ``OPENAI_API_KEY``, ``OPENAI_BASE_URL``, and model selection
via interactive click prompts. The base URL defaults to the official
OpenAI endpoint but can be overridden for compatible providers.

## Methods

- `def collect(self) -> ProviderConfig` — Collect OpenAI credentials interactively.
