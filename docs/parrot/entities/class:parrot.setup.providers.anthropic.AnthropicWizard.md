---
type: Wiki Entity
title: AnthropicWizard
id: class:parrot.setup.providers.anthropic.AnthropicWizard
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Wizard for Anthropic (Claude) credential collection.
relates_to:
- concept: class:parrot.setup.wizard.BaseClientWizard
  rel: extends
---

# AnthropicWizard

Defined in [`parrot.setup.providers.anthropic`](../summaries/mod:parrot.setup.providers.anthropic.md).

```python
class AnthropicWizard(BaseClientWizard)
```

Wizard for Anthropic (Claude) credential collection.

Collects the ``ANTHROPIC_API_KEY`` and model selection via
interactive click prompts.

## Methods

- `def collect(self) -> ProviderConfig` — Collect Anthropic credentials interactively.
