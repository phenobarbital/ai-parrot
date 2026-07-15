---
type: Wiki Summary
title: parrot_tools.scraping.drivers.selenium_driver
id: mod:parrot_tools.scraping.drivers.selenium_driver
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Selenium-based browser automation driver.
relates_to:
- concept: class:parrot_tools.scraping.drivers.selenium_driver.SeleniumDriver
  rel: defines
- concept: mod:parrot_tools.scraping.driver
  rel: references
- concept: mod:parrot_tools.scraping.drivers.abstract
  rel: references
---

# `parrot_tools.scraping.drivers.selenium_driver`

Selenium-based browser automation driver.

Wraps the existing :class:`SeleniumSetup` class to implement the
:class:`AbstractDriver` interface.  All blocking Selenium WebDriver calls
are dispatched via :func:`asyncio.get_running_loop().run_in_executor` so the
async event loop is never blocked.

The ``selenium`` package is imported lazily inside :meth:`start` so the
module can be loaded even when Selenium is not installed.

## Classes

- **`SeleniumDriver(AbstractDriver)`** — Selenium-based browser automation driver.
