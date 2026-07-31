---
type: Wiki Summary
title: parrot_tools.computer.models
id: mod:parrot_tools.computer.models
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Data models for the Computer-Use Agent feature (FEAT-227).
relates_to:
- concept: class:parrot_tools.computer.models.ComputerTask
  rel: defines
- concept: class:parrot_tools.computer.models.ComputerUseConfig
  rel: defines
- concept: class:parrot_tools.computer.models.EnvState
  rel: defines
- concept: class:parrot_tools.computer.models.LoopResult
  rel: defines
- concept: class:parrot_tools.computer.models.TaskResult
  rel: defines
---

# `parrot_tools.computer.models`

Data models for the Computer-Use Agent feature (FEAT-227).

All models are pure Pydantic v2 BaseModel subclasses with no external
dependencies beyond pydantic itself.

## Classes

- **`EnvState(BaseModel)`** — State returned after each computer-use action.
- **`ComputerUseConfig(BaseModel)`** — Configuration for the ComputerUse tool type in GoogleGenAIClient.
- **`ComputerTask(BaseModel)`** — A reusable sequence of natural-language instructions.
- **`TaskResult(BaseModel)`** — Result of a single task execution.
- **`LoopResult(BaseModel)`** — Result of a loop execution.
