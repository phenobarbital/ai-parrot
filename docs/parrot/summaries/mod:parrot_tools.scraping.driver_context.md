---
type: Wiki Summary
title: parrot_tools.scraping.driver_context
id: mod:parrot_tools.scraping.driver_context
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Driver Context Manager — manages browser driver lifecycle.
relates_to:
- concept: class:parrot_tools.scraping.driver_context.DriverRegistry
  rel: defines
- concept: func:parrot_tools.scraping.driver_context.driver_context
  rel: defines
- concept: mod:parrot_tools.scraping.drivers.abstract
  rel: references
- concept: mod:parrot_tools.scraping.drivers.playwright_config
  rel: references
- concept: mod:parrot_tools.scraping.drivers.playwright_driver
  rel: references
- concept: mod:parrot_tools.scraping.drivers.selenium_driver
  rel: references
- concept: mod:parrot_tools.scraping.toolkit_models
  rel: references
---

# `parrot_tools.scraping.driver_context`

Driver Context Manager — manages browser driver lifecycle.

Provides a plugin-style ``DriverRegistry`` for registering driver factories
and an async context manager ``driver_context()`` that handles session-based
(persistent) and per-operation (fresh) driver modes.

## Classes

- **`DriverRegistry`** — Plugin-style registry for browser driver factories.

## Functions

- `async def driver_context(config: DriverConfig, session_driver: Optional[Any]=None) -> AsyncIterator[Any]` — Async context manager that yields a browser driver.
