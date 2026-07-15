---
type: Wiki Entity
title: DriverFactory
id: class:parrot_tools.scraping.driver_factory.DriverFactory
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Factory for creating browser automation driver instances.
---

# DriverFactory

Defined in [`parrot_tools.scraping.driver_factory`](../summaries/mod:parrot_tools.scraping.driver_factory.md).

```python
class DriverFactory
```

Factory for creating browser automation driver instances.

Dispatches to the correct driver implementation based on configuration.
This is the single entry point for obtaining an ``AbstractDriver``.

Usage::

    driver = DriverFactory.create({"driver_type": "playwright", "browser": "chromium"})
    await driver.start()

## Methods

- `def create(config: Optional[Union[Dict[str, Any], Any]]=None) -> AbstractDriver` — Create and return an AbstractDriver based on configuration.
