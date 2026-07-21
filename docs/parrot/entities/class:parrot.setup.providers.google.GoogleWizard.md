---
type: Wiki Entity
title: GoogleWizard
id: class:parrot.setup.providers.google.GoogleWizard
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Wizard for Google (Gemini) credential collection.
relates_to:
- concept: class:parrot.setup.wizard.BaseClientWizard
  rel: extends
---

# GoogleWizard

Defined in [`parrot.setup.providers.google`](../summaries/mod:parrot.setup.providers.google.md).

```python
class GoogleWizard(BaseClientWizard)
```

Wizard for Google (Gemini) credential collection.

Collects the ``GOOGLE_API_KEY`` and model selection via
interactive click prompts.

## Methods

- `def collect(self) -> ProviderConfig` — Collect Google credentials interactively.
