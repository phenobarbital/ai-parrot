---
type: Wiki Summary
title: parrot.models.basic
id: mod:parrot.models.basic
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module parrot.models.basic
relates_to:
- concept: class:parrot.models.basic.CompletionUsage
  rel: defines
- concept: class:parrot.models.basic.ModelConfig
  rel: defines
- concept: class:parrot.models.basic.OutputFormat
  rel: defines
- concept: class:parrot.models.basic.ToolCall
  rel: defines
- concept: class:parrot.models.basic.ToolConfig
  rel: defines
---

# `parrot.models.basic`

## Classes

- **`OutputFormat(Enum)`** — Supported output formats for structured responses.
- **`ToolCall(BaseModel)`** — Unified tool call representation.
- **`ToolConfig(BaseModel)`** — Tool configuration for session-scoped ToolManager setup.
- **`ModelConfig(BaseModel)`** — Model configuration for session-scoped LLM setup.
- **`CompletionUsage(BaseModel)`** — Unified completion usage tracking across different LLM providers.
