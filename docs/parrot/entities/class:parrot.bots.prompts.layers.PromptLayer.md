---
type: Wiki Entity
title: PromptLayer
id: class:parrot.bots.prompts.layers.PromptLayer
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Single composable prompt layer.
---

# PromptLayer

Defined in [`parrot.bots.prompts.layers`](../summaries/mod:parrot.bots.prompts.layers.md).

```python
class PromptLayer
```

Single composable prompt layer.

Attributes:
    name: Unique identifier for this layer.
    priority: Rendering order (lower = earlier in prompt).
    template: XML template with $variable placeholders.
    phase: When to resolve variables (CONFIGURE or REQUEST).
    condition: Optional callable; layer is skipped if it returns False.
    required_vars: Set of variable names that must be present.
    cacheable: Whether this layer is eligible for provider-side prompt
        caching (FEAT-181). Defaults to ``True`` for CONFIGURE-phase
        layers and ``False`` for REQUEST-phase layers. Can be explicitly
        overridden per-layer by passing ``cacheable=False`` (or ``True``).

## Methods

- `def render(self, context: Dict[str, Any]) -> Optional[str]` — Render this layer with the given context.
- `def partial_render(self, context: Dict[str, Any]) -> PromptLayer` — Render only the variables present in context, return a new layer
