---
type: Wiki Summary
title: parrot_tools.flowtask.tool
id: mod:parrot_tools.flowtask.tool
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: FlowtaskToolkit for AI-Parrot - Execute Flowtask components and tasks dynamically.
relates_to:
- concept: class:parrot_tools.flowtask.tool.FlowtaskCodeExecutionInput
  rel: defines
- concept: class:parrot_tools.flowtask.tool.FlowtaskComponentInput
  rel: defines
- concept: class:parrot_tools.flowtask.tool.FlowtaskListTasksInput
  rel: defines
- concept: class:parrot_tools.flowtask.tool.FlowtaskRemoteExecutionInput
  rel: defines
- concept: class:parrot_tools.flowtask.tool.FlowtaskTaskExecutionInput
  rel: defines
- concept: class:parrot_tools.flowtask.tool.FlowtaskTaskServiceInput
  rel: defines
- concept: class:parrot_tools.flowtask.tool.FlowtaskToolkit
  rel: defines
- concept: class:parrot_tools.flowtask.tool.TaskCodeFormat
  rel: defines
- concept: mod:parrot._imports
  rel: references
- concept: mod:parrot_tools.decorators
  rel: references
- concept: mod:parrot_tools.toolkit
  rel: references
---

# `parrot_tools.flowtask.tool`

FlowtaskToolkit for AI-Parrot - Execute Flowtask components and tasks dynamically.

This toolkit provides tools for:
- Running individual Flowtask components with custom input data
- Executing local Flowtask tasks
- Calling remote Flowtask API endpoints
- Running tasks from JSON/YAML code definitions

``flowtask`` is an optional dependency. Install with: pip install ai-parrot[flowtask]

## Classes

- **`FlowtaskComponentInput(BaseModel)`** — Input schema for component_call tool.
- **`FlowtaskTaskExecutionInput(BaseModel)`** — Input schema for task_execution tool.
- **`FlowtaskRemoteExecutionInput(BaseModel)`** — Input schema for remote_execution tool.
- **`TaskCodeFormat(str, Enum)`** — Format of the task code.
- **`FlowtaskCodeExecutionInput(BaseModel)`** — Input schema for code_execution tool.
- **`FlowtaskTaskServiceInput(BaseModel)`** — Input schema for task_service tool (synchronous REST execution).
- **`FlowtaskListTasksInput(BaseModel)`** — Input schema for list_tasks tool (task discovery).
- **`FlowtaskToolkit(AbstractToolkit)`** — Toolkit for executing Flowtask components and tasks dynamically.
