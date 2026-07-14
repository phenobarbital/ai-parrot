---
type: Wiki Entity
title: SubprocessExecutor
id: class:parrot_tools.codeinterpreter.executor.SubprocessExecutor
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Fallback executor using subprocess with basic restrictions.
---

# SubprocessExecutor

Defined in [`parrot_tools.codeinterpreter.executor`](../summaries/mod:parrot_tools.codeinterpreter.executor.md).

```python
class SubprocessExecutor
```

Fallback executor using subprocess with basic restrictions.
WARNING: Less secure than Docker-based isolation.

## Methods

- `def execute_code(self, code: str, working_dir: Optional[Path]=None, additional_files: Optional[Dict[str, str]]=None) -> ExecutionResult` — Execute code using subprocess
- `def validate_syntax(self, code: str) -> Tuple[bool, Optional[str]]` — Validate Python syntax
- `def cleanup(self)` — No cleanup needed for subprocess executor
