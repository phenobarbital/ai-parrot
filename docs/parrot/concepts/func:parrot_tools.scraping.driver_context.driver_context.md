---
type: Concept
title: driver_context()
id: func:parrot_tools.scraping.driver_context.driver_context
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Async context manager that yields a browser driver.
---

# driver_context

```python
async def driver_context(config: DriverConfig, session_driver: Optional[Any]=None) -> AsyncIterator[Any]
```

Async context manager that yields a browser driver.

In session mode (``session_driver`` provided), the existing driver is
yielded without lifecycle management. In fresh mode, a new driver is
created from the registry, yielded, and quit on exit.

Args:
    config: Driver configuration.
    session_driver: Existing driver to reuse (session mode). If ``None``,
        a fresh driver is created and destroyed.

Yields:
    A browser driver instance.
