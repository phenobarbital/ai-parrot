---
type: Wiki Summary
title: parrot_tools.codeinterpreter.executor
id: mod:parrot_tools.codeinterpreter.executor
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Isolated code execution environment using Docker containers.
relates_to:
- concept: class:parrot_tools.codeinterpreter.executor.ExecutionResult
  rel: defines
- concept: class:parrot_tools.codeinterpreter.executor.IsolatedExecutor
  rel: defines
- concept: class:parrot_tools.codeinterpreter.executor.SubprocessExecutor
  rel: defines
- concept: func:parrot_tools.codeinterpreter.executor.create_executor
  rel: defines
---

# `parrot_tools.codeinterpreter.executor`

Isolated code execution environment using Docker containers.
Provides secure Python code execution with resource limits and timeout controls.

## Classes

- **`ExecutionResult`** — Result from code execution in isolated environment
- **`IsolatedExecutor`** — Manages isolated Python code execution using Docker containers.
- **`SubprocessExecutor`** — Fallback executor using subprocess with basic restrictions.

## Functions

- `def create_executor(use_docker: bool=True, **kwargs) -> IsolatedExecutor | SubprocessExecutor` — Factory function to create appropriate executor.
