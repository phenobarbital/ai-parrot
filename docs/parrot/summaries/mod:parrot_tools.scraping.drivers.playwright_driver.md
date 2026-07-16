---
type: Wiki Summary
title: parrot_tools.scraping.drivers.playwright_driver
id: mod:parrot_tools.scraping.drivers.playwright_driver
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Playwright-based browser automation driver.
relates_to:
- concept: class:parrot_tools.scraping.drivers.playwright_driver.PlaywrightDriver
  rel: defines
- concept: mod:parrot_tools.scraping.drivers.abstract
  rel: references
- concept: mod:parrot_tools.scraping.drivers.playwright_config
  rel: references
---

# `parrot_tools.scraping.drivers.playwright_driver`

Playwright-based browser automation driver.

Implements :class:`AbstractDriver` using Playwright's async API, providing
full browser automation with Playwright-exclusive features such as request
interception, HAR recording, tracing, PDF export, and session persistence.

## Classes

- **`PlaywrightDriver(AbstractDriver)`** — Playwright-based browser automation driver.
