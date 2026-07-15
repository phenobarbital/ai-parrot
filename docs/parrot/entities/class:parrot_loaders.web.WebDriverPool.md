---
type: Wiki Entity
title: WebDriverPool
id: class:parrot_loaders.web.WebDriverPool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Async WebDriver pool for efficient browser management.
---

# WebDriverPool

Defined in [`parrot_loaders.web`](../summaries/mod:parrot_loaders.web.md).

```python
class WebDriverPool
```

Async WebDriver pool for efficient browser management.

## Methods

- `async def get_driver(self) -> webdriver` — Get a driver from the pool or create a new one.
- `async def return_driver(self, driver: webdriver)` — Return a driver to the pool after cleaning it.
- `async def close_all(self)` — Close all drivers in the pool.
