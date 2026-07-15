---
type: Wiki Entity
title: IsolatedExecutor
id: class:parrot_tools.codeinterpreter.executor.IsolatedExecutor
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Manages isolated Python code execution using Docker containers.
---

# IsolatedExecutor

Defined in [`parrot_tools.codeinterpreter.executor`](../summaries/mod:parrot_tools.codeinterpreter.executor.md).

```python
class IsolatedExecutor
```

Manages isolated Python code execution using Docker containers.

Features:
- Resource limits (memory, CPU)
- Execution timeout
- Network isolation
- Read-only filesystem (except work directory)
- Container reuse for better performance

## Methods

- `def execute_code(self, code: str, working_dir: Optional[Path]=None, additional_files: Optional[Dict[str, str]]=None) -> ExecutionResult` — Execute Python code in an isolated Docker container.
- `def execute_tests(self, test_code: str, source_code: Optional[str]=None, requirements: Optional[list[str]]=None) -> ExecutionResult` — Execute pytest tests in isolated environment.
- `def validate_syntax(self, code: str) -> Tuple[bool, Optional[str]]` — Validate Python syntax without executing.
- `def cleanup(self)` — Clean up Docker resources
