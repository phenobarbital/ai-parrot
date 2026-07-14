---
type: Wiki Entity
title: OpenRouterWizard
id: class:parrot.setup.providers.openrouter.OpenRouterWizard
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Wizard for OpenRouter credential collection.
relates_to:
- concept: class:parrot.setup.wizard.BaseClientWizard
  rel: extends
---

# OpenRouterWizard

Defined in [`parrot.setup.providers.openrouter`](../summaries/mod:parrot.setup.providers.openrouter.md).

```python
class OpenRouterWizard(BaseClientWizard)
```

Wizard for OpenRouter credential collection.

Collects the ``OPENROUTER_API_KEY`` and model selection via
interactive click prompts. OpenRouter uses a ``provider/model``
format for model identifiers.

## Methods

- `def collect(self) -> ProviderConfig` — Collect OpenRouter credentials interactively.
