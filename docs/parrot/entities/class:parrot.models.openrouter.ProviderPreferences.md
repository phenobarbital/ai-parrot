---
type: Wiki Entity
title: ProviderPreferences
id: class:parrot.models.openrouter.ProviderPreferences
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: OpenRouter provider routing preferences.
---

# ProviderPreferences

Defined in [`parrot.models.openrouter`](../summaries/mod:parrot.models.openrouter.md).

```python
class ProviderPreferences(BaseModel)
```

OpenRouter provider routing preferences.

Controls how OpenRouter selects upstream providers for model inference.
Serialized and sent as the 'provider' key in extra_body.

Attributes:
    allow_fallbacks: Allow OpenRouter to fall back to alternative providers.
    require_parameters: Only use providers that support all requested parameters.
    data_collection: Data collection preference: 'deny' or 'allow'.
    order: Ordered list of preferred providers, e.g. ['DeepInfra', 'Together'].
    ignore: List of providers to exclude from routing.
    quantizations: Allowed quantization levels, e.g. ['bf16', 'fp8'].
