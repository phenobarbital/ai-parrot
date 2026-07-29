---
type: Concept
title: retry_on_errors()
id: func:parrot.mcp.context.retry_on_errors
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Decorator for automatic retry on transient errors with exponential backoff.
---

# retry_on_errors

```python
def retry_on_errors(max_retries: int=3, base_wait: float=2.0) -> Callable[[F], F]
```

Decorator for automatic retry on transient errors with exponential backoff.

Args:
    max_retries: Maximum number of retry attempts (default: 3)
    base_wait: Base wait time in seconds for exponential backoff (default: 2.0)

Returns:
    Decorated async function with retry logic

Example:
    >>> @retry_on_errors(max_retries=3)
    ... async def get_tools(self):
    ...     # This will auto-retry on TransientMCPError
    ...     return await self._session.list_tools()
