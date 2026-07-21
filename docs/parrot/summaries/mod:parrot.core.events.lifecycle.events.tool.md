---
type: Wiki Summary
title: parrot.core.events.lifecycle.events.tool
id: mod:parrot.core.events.lifecycle.events.tool
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Tool lifecycle events.
relates_to:
- concept: class:parrot.core.events.lifecycle.events.tool.AfterToolCallEvent
  rel: defines
- concept: class:parrot.core.events.lifecycle.events.tool.BeforeToolCallEvent
  rel: defines
- concept: class:parrot.core.events.lifecycle.events.tool.ToolCallFailedEvent
  rel: defines
- concept: mod:parrot.core.events.lifecycle.base
  rel: references
---

# `parrot.core.events.lifecycle.events.tool`

Tool lifecycle events.

FEAT-176 — Lifecycle Events System.

Covers: before/after/failed AbstractTool.execute() calls.

## Classes

- **`BeforeToolCallEvent(LifecycleEvent)`** — Emitted just before AbstractTool._execute() is called.
- **`AfterToolCallEvent(LifecycleEvent)`** — Emitted after AbstractTool._execute() completes successfully.
- **`ToolCallFailedEvent(LifecycleEvent)`** — Emitted when AbstractTool._execute() raises an exception.
