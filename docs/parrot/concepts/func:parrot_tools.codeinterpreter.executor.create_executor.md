---
type: Concept
title: create_executor()
id: func:parrot_tools.codeinterpreter.executor.create_executor
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Factory function to create appropriate executor.
---

# create_executor

```python
def create_executor(use_docker: bool=True, **kwargs) -> IsolatedExecutor | SubprocessExecutor
```

Factory function to create appropriate executor.

Args:
    use_docker: Whether to use Docker (falls back to subprocess if Docker unavailable)
    **kwargs: Additional arguments for executor

Returns:
    Executor instance
