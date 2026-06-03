---
id: F006
query_id: Q004
type: read
intent: Understand PlaywrightDriver context/page management for multi-window FlowExecutor
executed_at: 2026-06-04T00:00:00Z
duration_ms: 52786
parent_id: null
depth: 0
---

# F006 — PlaywrightDriver supports single context only; FlowExecutor needs direct Playwright access

## Summary

`PlaywrightDriver` (playwright_driver.py:15-395) creates ONE `BrowserContext` and ONE initial `Page` in `start()`. It has `new_page()` (line 330-339) that creates additional pages in the SAME context. No method to create additional contexts, and no `close_page()` method. `AbstractDriver` (abstract.py:11-352) has 19 abstract methods but exposes NO context/page management — it's a flat, single-page interface.

This means the FlowExecutor CANNOT use `AbstractDriver`/`PlaywrightDriver` as-is for multi-session flows. It must either:
(a) Work directly with Playwright's `Browser` object to create multiple `BrowserContext`s, then wrap each Page in a lightweight driver adapter, or
(b) Extend AbstractDriver with context management methods.

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py`
  lines: 41-64
  symbol: `PlaywrightDriver.start`
  excerpt: |
    async def start(self):
        self._playwright = await async_playwright().start()
        self._browser = await getattr(self._playwright, self._config.browser_type).launch(headless=...)
        self._context = await self._browser.new_context(**context_kwargs)
        self._page = await self._context.new_page()

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py`
  lines: 330-339
  symbol: `PlaywrightDriver.new_page`
  excerpt: |
    async def new_page(self):
        self._page = await self._context.new_page()
        return self._page

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py`
  lines: 11-352
  symbol: `AbstractDriver`
  excerpt: |
    class AbstractDriver(ABC):
        # 19 abstract methods: start, quit, navigate, click, fill, ...
        # No context/page management in the interface

## Notes

This is the biggest architectural gap. The brainstorm says "envuelve la Page en un AbstractDriver" but PlaywrightDriver is not designed for this — it owns its browser lifecycle. A lightweight `PageDriver` adapter wrapping a Playwright Page (implementing AbstractDriver's interface by delegating to the Page) would be the cleanest solution. This keeps execute_plan_steps unchanged while supporting multi-context.
