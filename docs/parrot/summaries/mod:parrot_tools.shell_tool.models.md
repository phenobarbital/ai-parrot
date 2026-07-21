---
type: Wiki Summary
title: parrot_tools.shell_tool.models
id: mod:parrot_tools.shell_tool.models
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module parrot_tools.shell_tool.models
relates_to:
- concept: class:parrot_tools.shell_tool.models.ActionResult
  rel: defines
- concept: class:parrot_tools.shell_tool.models.BaseAction
  rel: defines
- concept: class:parrot_tools.shell_tool.models.CommandObject
  rel: defines
- concept: class:parrot_tools.shell_tool.models.PlanStep
  rel: defines
- concept: class:parrot_tools.shell_tool.models.ShellToolArgs
  rel: defines
- concept: mod:parrot_tools.abstract
  rel: references
---

# `parrot_tools.shell_tool.models`

## Classes

- **`CommandObject(BaseModel)`** — Represents a shell command to be executed.
- **`PlanStep(BaseModel)`** — Represents a step in a shell command plan.
- **`ShellToolArgs(AbstractToolArgsSchema)`** — Arguments for the ShellTool.
- **`ActionResult`** — Result of a shell action execution.
- **`BaseAction`** — Base class for shell and utility actions.
