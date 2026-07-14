---
type: Wiki Summary
title: parrot_tools.scraping.driver_factory
id: mod:parrot_tools.scraping.driver_factory
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Factory for creating browser automation driver instances.
relates_to:
- concept: class:parrot_tools.scraping.driver_factory.DriverFactory
  rel: defines
- concept: mod:parrot_tools.scraping.drivers.abstract
  rel: references
- concept: mod:parrot_tools.scraping.drivers.playwright_config
  rel: references
- concept: mod:parrot_tools.scraping.drivers.playwright_driver
  rel: references
- concept: mod:parrot_tools.scraping.drivers.selenium_driver
  rel: references
---

# `parrot_tools.scraping.driver_factory`

Factory for creating browser automation driver instances.

Provides :class:`DriverFactory` as the single entry point for obtaining a
properly configured :class:`AbstractDriver`.  Consumers call
``DriverFactory.create(config)`` instead of instantiating driver classes
directly.

Both ``PlaywrightDriver`` and ``SeleniumDriver`` are imported lazily so the
module works even when only one library is installed.

## Classes

- **`DriverFactory`** — Factory for creating browser automation driver instances.
