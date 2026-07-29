---
type: Wiki Entity
title: VoiceConfig
id: class:parrot.voice.models.VoiceConfig
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Configuration for voice sessions.
---

# VoiceConfig

Defined in [`parrot.voice.models`](../summaries/mod:parrot.voice.models.md).

```python
class VoiceConfig
```

Configuration for voice sessions.

Defines audio parameters, provider settings, and behavior options.

## Methods

- `def get_model(self) -> str` — Get the appropriate model string for the provider.
- `def to_gemini_config(self) -> Dict[str, Any]` — Convert to Gemini Live API configuration format.
