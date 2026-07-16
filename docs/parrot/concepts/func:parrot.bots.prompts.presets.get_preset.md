---
type: Concept
title: get_preset()
id: func:parrot.bots.prompts.presets.get_preset
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Get a preset by name. Returns a fresh builder each time.
---

# get_preset

```python
def get_preset(name: str) -> PromptBuilder
```

Get a preset by name. Returns a fresh builder each time.

Args:
    name: The preset name.

Returns:
    A new PromptBuilder instance from the named factory.

Raises:
    KeyError: If the preset name is not registered.
