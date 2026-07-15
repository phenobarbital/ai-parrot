---
type: Wiki Summary
title: parrot.bots.prompts.layers
id: mod:parrot.bots.prompts.layers
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Composable prompt layer system.
relates_to:
- concept: class:parrot.bots.prompts.layers.LayerPriority
  rel: defines
- concept: class:parrot.bots.prompts.layers.PromptLayer
  rel: defines
- concept: class:parrot.bots.prompts.layers.RenderPhase
  rel: defines
---

# `parrot.bots.prompts.layers`

Composable prompt layer system.

Defines the core PromptLayer dataclass and all built-in layers that replace
the monolithic prompt templates (BASIC_SYSTEM_PROMPT, AGENT_PROMPT, etc.).

Each layer is an immutable, composable unit with:
- A priority that determines rendering order
- A template using $variable placeholders (string.Template)
- A phase (CONFIGURE or REQUEST) controlling when variables resolve
- An optional condition for conditional inclusion

See spec: sdd/specs/composable-prompt-layer.spec.md (Sections 3.1, 3.2)

## Classes

- **`LayerPriority(IntEnum)`** — Execution order. Lower = rendered first in the prompt.
- **`RenderPhase(str, Enum)`** — When a layer's variables get resolved.
- **`PromptLayer`** — Single composable prompt layer.
