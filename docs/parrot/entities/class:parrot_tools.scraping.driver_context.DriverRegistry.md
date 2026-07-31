---
type: Wiki Entity
title: DriverRegistry
id: class:parrot_tools.scraping.driver_context.DriverRegistry
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Plugin-style registry for browser driver factories.
---

# DriverRegistry

Defined in [`parrot_tools.scraping.driver_context`](../summaries/mod:parrot_tools.scraping.driver_context.md).

```python
class DriverRegistry
```

Plugin-style registry for browser driver factories.

Driver factories are callables that accept a ``DriverConfig`` and return
a setup object with an ``async def get_driver()`` method.

Usage::

    DriverRegistry.register("selenium", my_selenium_factory)
    factory = DriverRegistry.get("selenium")

## Methods

- `def register(cls, driver_type: str, factory: Callable[[DriverConfig], Any]) -> None` — Register a driver factory for a given driver type.
- `def unregister(cls, driver_type: str) -> None` — Remove a registered driver factory.
- `def get(cls, driver_type: str) -> Callable[[DriverConfig], Any]` — Get a registered driver factory.
- `def list_registered(cls) -> list[str]` — Return list of registered driver type names.
