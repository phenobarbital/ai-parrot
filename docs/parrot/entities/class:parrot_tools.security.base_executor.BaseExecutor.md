---
type: Wiki Entity
title: BaseExecutor
id: class:parrot_tools.security.base_executor.BaseExecutor
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Abstract base executor for Docker or CLI process management.
---

# BaseExecutor

Defined in [`parrot_tools.security.base_executor`](../summaries/mod:parrot_tools.security.base_executor.md).

```python
class BaseExecutor(ABC)
```

Abstract base executor for Docker or CLI process management.

Provides common functionality for running security scanners:
- Environment variable building for cloud credentials
- Docker and direct CLI command construction
- Async subprocess execution with timeout
- Credential masking for safe logging

Subclasses must implement:
- _build_cli_args(): Build scanner-specific CLI arguments
- _default_cli_name(): Return the default CLI binary name

## Methods

- `async def execute(self, args: Optional[list[str]]=None, **kwargs) -> tuple[str, str, int]` — Run the scanner and return output.
- `async def execute_streaming(self, progress_callback: Callable[[str], None] | None=None, args: list[str] | None=None, **kwargs) -> tuple[str, str, int]` — Run the scanner with real-time stderr streaming.
