---
type: Wiki Entity
title: PythonExecutionTool
id: class:parrot_tools.codeinterpreter.internals.PythonExecutionTool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Tool for executing Python code in isolated environment.
---

# PythonExecutionTool

Defined in [`parrot_tools.codeinterpreter.internals`](../summaries/mod:parrot_tools.codeinterpreter.internals.md).

```python
class PythonExecutionTool
```

Tool for executing Python code in isolated environment.
This wraps the IsolatedExecutor for use by the agent.

## Methods

- `def execute(self, code: str, description: str='Execute Python code') -> Dict[str, Any]` — Execute Python code and return results.
- `def execute_tests(self, test_code: str, source_code: Optional[str]=None) -> Dict[str, Any]` — Execute pytest tests.
