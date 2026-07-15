---
type: Wiki Summary
title: parrot.outputs.formats
id: mod:parrot.outputs.formats
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Module parrot.outputs.formats
relates_to:
- concept: class:parrot.outputs.formats.Renderer
  rel: defines
- concept: func:parrot.outputs.formats.get_infographic_html_renderer
  rel: defines
- concept: func:parrot.outputs.formats.get_output_prompt
  rel: defines
- concept: func:parrot.outputs.formats.get_renderer
  rel: defines
- concept: func:parrot.outputs.formats.has_system_prompt
  rel: defines
- concept: func:parrot.outputs.formats.register_renderer
  rel: defines
- concept: mod:parrot.outputs
  rel: references
---

# `parrot.outputs.formats`

## Classes

- **`Renderer(Protocol)`** — Protocol for output renderers.

## Functions

- `def register_renderer(mode: OutputMode, system_prompt: Optional[str]=None)` — Decorator to register a renderer class and optionally its system prompt.
- `def get_renderer(mode: OutputMode) -> Type[Renderer]` — Get the renderer class for the given output mode.
- `def get_output_prompt(mode: OutputMode) -> Optional[str]` — Get system prompt for mode.
- `def has_system_prompt(mode: OutputMode) -> bool` — Check if mode has a registered system prompt.
- `def get_infographic_html_renderer()` — Return ``InfographicHTMLRenderer`` with its concrete type preserved.
