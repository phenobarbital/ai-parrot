---
type: Wiki Summary
title: parrot_tools.codeinterpreter.internals
id: mod:parrot_tools.codeinterpreter.internals
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Internal tools for the CodeInterpreterTool agent.
relates_to:
- concept: class:parrot_tools.codeinterpreter.internals.ClassInfo
  rel: defines
- concept: class:parrot_tools.codeinterpreter.internals.FileOperationsTool
  rel: defines
- concept: class:parrot_tools.codeinterpreter.internals.FunctionInfo
  rel: defines
- concept: class:parrot_tools.codeinterpreter.internals.ImportInfo
  rel: defines
- concept: class:parrot_tools.codeinterpreter.internals.PythonExecutionTool
  rel: defines
- concept: class:parrot_tools.codeinterpreter.internals.StaticAnalysisTool
  rel: defines
- concept: func:parrot_tools.codeinterpreter.internals.calculate_code_hash
  rel: defines
---

# `parrot_tools.codeinterpreter.internals`

Internal tools for the CodeInterpreterTool agent.
These tools provide the agent with capabilities for static analysis,
code execution, and file operations.

## Classes

- **`FunctionInfo`** — Information about a function
- **`ClassInfo`** — Information about a class
- **`ImportInfo`** — Information about an import
- **`StaticAnalysisTool`** — Tool for performing static analysis on Python code.
- **`PythonExecutionTool`** — Tool for executing Python code in isolated environment.
- **`FileOperationsTool`** — Tool for file operations (reading, writing, organizing outputs).

## Functions

- `def calculate_code_hash(code: str) -> str` — Calculate SHA-256 hash of code.
