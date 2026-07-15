---
type: Wiki Summary
title: parrot.tools.abstract
id: mod:parrot.tools.abstract
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Abstract Tool base class for all function-calling tools.in ai-parrot framework.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: defines
- concept: class:parrot.tools.abstract.AbstractToolArgsSchema
  rel: defines
- concept: class:parrot.tools.abstract.ToolResult
  rel: defines
- concept: func:parrot.tools.abstract.current_credential
  rel: defines
- concept: mod:parrot.auth.broker
  rel: references
- concept: mod:parrot.auth.credentials
  rel: references
- concept: mod:parrot.auth.exceptions
  rel: references
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.core.events.lifecycle.events
  rel: references
- concept: mod:parrot.core.events.lifecycle.mixin
  rel: references
- concept: mod:parrot.core.events.lifecycle.trace
  rel: references
- concept: mod:parrot.security.redaction
  rel: references
- concept: mod:parrot.tools.executors.abstract
  rel: references
---

# `parrot.tools.abstract`

Abstract Tool base class for all function-calling tools.in ai-parrot framework.

## Classes

- **`AbstractToolArgsSchema(BaseModel)`** — Base schema for tool arguments.
- **`ToolResult(BaseModel)`** — Standardized tool result format.
- **`AbstractTool(EventEmitterMixin, ABC)`** — Abstract base class for all tools in the ai-parrot framework.

## Functions

- `def current_credential() -> Optional[Any]` — Return the per-call credential injected by the broker, or ``None``.
