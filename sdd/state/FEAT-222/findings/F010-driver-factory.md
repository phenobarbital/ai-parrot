---
id: F010
query_id: Q004
type: read
intent: Understand DriverFactory for FlowExecutor's driver creation needs
executed_at: 2026-06-04T00:00:00Z
duration_ms: 52786
parent_id: null
depth: 0
---

# F010 — DriverFactory creates standalone drivers; not suitable for FlowExecutor's per-Page needs

## Summary

`DriverFactory.create(config)` (driver_factory.py:31-148) is a static method that returns an AbstractDriver instance (not started). For Playwright, it maps browser names and creates a `PlaywrightDriver(PlaywrightConfig)`. The factory always creates a NEW browser instance. For FlowExecutor, which needs multiple Pages within shared BrowserContexts, the factory is too coarse — it creates an entire browser per call. FlowExecutor should manage a single Browser instance and create BrowserContexts/Pages directly.

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/driver_factory.py`
  lines: 31-148
  symbol: `DriverFactory.create`
  excerpt: |
    @staticmethod
    def create(config=None) -> AbstractDriver:
        # For playwright: maps browser, builds PlaywrightConfig, returns PlaywrightDriver
        # For selenium: returns SeleniumDriver
        # Always creates a new standalone driver

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py`
  lines: 41-64
  symbol: `PlaywrightDriver.start`
  excerpt: |
    # Creates: playwright instance → browser → single context → single page

## Notes

FlowExecutor needs a "session manager" that owns the Browser instance and vends BrowserContexts by session label. Each context produces Pages that get wrapped in lightweight PageDriver adapters for use with execute_plan_steps. This is a new component not present in the codebase.
