---
type: Wiki Entity
title: StaticAnalysisTool
id: class:parrot_tools.codeinterpreter.internals.StaticAnalysisTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Tool for performing static analysis on Python code.
---

# StaticAnalysisTool

Defined in [`parrot_tools.codeinterpreter.internals`](../summaries/mod:parrot_tools.codeinterpreter.internals.md).

```python
class StaticAnalysisTool
```

Tool for performing static analysis on Python code.
Uses AST parsing and radon for complexity metrics.

## Methods

- `def analyze_code_structure(self, code: str) -> Dict[str, Any]` — Analyze code structure using AST.
- `def calculate_complexity(self, code: str) -> Dict[str, Any]` — Calculate code complexity metrics using radon.
