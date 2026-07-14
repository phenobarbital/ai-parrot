---
type: Wiki Summary
title: parrot.human.tool
id: mod:parrot.human.tool
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: HumanTool — an AbstractTool that asks a human for input.
relates_to:
- concept: class:parrot.human.tool.HumanTool
  rel: defines
- concept: class:parrot.human.tool.HumanToolInput
  rel: defines
- concept: mod:parrot.core.exceptions
  rel: references
- concept: mod:parrot.human.models
  rel: references
- concept: mod:parrot.tools.abstract
  rel: references
---

# `parrot.human.tool`

HumanTool — an AbstractTool that asks a human for input.

## Classes

- **`HumanToolInput(AbstractToolArgsSchema)`** — Input schema for the HumanTool.
- **`HumanTool(AbstractTool)`** — Tool that pauses agent execution to request human input.
