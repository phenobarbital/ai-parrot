---
type: Wiki Entity
title: XAIWizard
id: class:parrot.setup.providers.xai.XAIWizard
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Wizard for xAI (Grok) credential collection.
relates_to:
- concept: class:parrot.setup.wizard.BaseClientWizard
  rel: extends
---

# XAIWizard

Defined in [`parrot.setup.providers.xai`](../summaries/mod:parrot.setup.providers.xai.md).

```python
class XAIWizard(BaseClientWizard)
```

Wizard for xAI (Grok) credential collection.

Collects the ``XAI_API_KEY`` and model selection via
interactive click prompts.

## Methods

- `def collect(self) -> ProviderConfig` — Collect xAI credentials interactively.
