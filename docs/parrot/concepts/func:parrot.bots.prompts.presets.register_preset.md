---
type: Concept
title: register_preset()
id: func:parrot.bots.prompts.presets.register_preset
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Register a named preset.
---

# register_preset

```python
def register_preset(name: str, factory: Callable[[], PromptBuilder]) -> None
```

Register a named preset.

Args:
    name: The preset name (e.g., "my-custom-preset").
    factory: A callable that returns a fresh PromptBuilder instance.
