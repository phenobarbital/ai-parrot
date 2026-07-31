---
type: Concept
title: register_renderer()
id: func:parrot.outputs.formats.register_renderer
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Decorator to register a renderer class and optionally its system prompt.
---

# register_renderer

```python
def register_renderer(mode: OutputMode, system_prompt: Optional[str]=None)
```

Decorator to register a renderer class and optionally its system prompt.

Args:
    mode: OutputMode enum value
    system_prompt: Optional system prompt to inject when using this mode
