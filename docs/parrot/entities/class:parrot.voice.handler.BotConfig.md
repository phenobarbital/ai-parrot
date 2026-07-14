---
type: Wiki Entity
title: BotConfig
id: class:parrot.voice.handler.BotConfig
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Configuration for VoiceBot creation.
---

# BotConfig

Defined in [`parrot.voice.handler`](../summaries/mod:parrot.voice.handler.md).

```python
class BotConfig
```

Configuration for VoiceBot creation.

## Methods

- `def as_dict(self) -> Dict[str, Any]` — Convert to dictionary, excluding None values.
- `def merge_with(self, overrides: Dict[str, Any]) -> 'BotConfig'` — Create new BotConfig with overrides applied.
- `def from_dict(cls, data: Dict[str, Any]) -> 'BotConfig'` — Create BotConfig from dictionary.
