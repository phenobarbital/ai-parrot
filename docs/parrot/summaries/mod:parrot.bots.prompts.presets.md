---
type: Wiki Summary
title: parrot.bots.prompts.presets
id: mod:parrot.bots.prompts.presets
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Preset registry for common PromptBuilder configurations.
relates_to:
- concept: func:parrot.bots.prompts.presets.get_preset
  rel: defines
- concept: func:parrot.bots.prompts.presets.list_presets
  rel: defines
- concept: func:parrot.bots.prompts.presets.register_preset
  rel: defines
- concept: mod:parrot.bots.prompts
  rel: references
---

# `parrot.bots.prompts.presets`

Preset registry for common PromptBuilder configurations.

Provides named factory functions so YAML agent definitions and BotManager
can reference prompt stacks by name (e.g., "default", "voice", "agent").

See spec: sdd/specs/composable-prompt-layer.spec.md (Section 3.4)

## Functions

- `def register_preset(name: str, factory: Callable[[], PromptBuilder]) -> None` — Register a named preset.
- `def get_preset(name: str) -> PromptBuilder` — Get a preset by name. Returns a fresh builder each time.
- `def list_presets() -> list[str]` — List available preset names.
