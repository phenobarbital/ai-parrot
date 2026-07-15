---
type: Wiki Summary
title: parrot_tools.scraping.drivers.page_driver
id: mod:parrot_tools.scraping.drivers.page_driver
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: PageDriver — a lightweight AbstractDriver over a single Playwright Page.
relates_to:
- concept: class:parrot_tools.scraping.drivers.page_driver.PageDriver
  rel: defines
- concept: mod:parrot_tools.scraping.drivers.abstract
  rel: references
---

# `parrot_tools.scraping.drivers.page_driver`

PageDriver — a lightweight AbstractDriver over a single Playwright Page.

``FlowExecutor`` creates one Playwright ``Page`` per node (from a
session-scoped ``BrowserContext``) and wraps it in a :class:`PageDriver` so it
can be handed to ``execute_plan_steps`` (which only speaks ``AbstractDriver``).

Unlike :class:`PlaywrightDriver`, this adapter owns neither the browser nor the
context — ``start()`` is a no-op and ``quit()`` closes only the wrapped page
(FEAT-222, Module 6).

## Classes

- **`PageDriver(AbstractDriver)`** — Adapt a live Playwright ``Page`` to the :class:`AbstractDriver` interface.
