---
id: F002
query_id: Q002
type: read
intent: Read driver factory and Playwright configuration
executed_at: 2026-09-05T13:52:00Z
depth: 0
parent_id: null
---

# F002 — Playwright configuration currently models launch, not CDP attach

## Summary

`PlaywrightConfig` contains browser type, headless mode, proxy, context settings, storage state, persistent profile, and channel fields. `PlaywrightDriver.start` always starts Playwright and launches a browser or persistent context; it does not currently expose a CDP endpoint or connect-over-CDP branch. This is the narrowest repository change needed for an Obscura-backed Playwright path.

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_config.py`
  lines: 12-73
  symbol: `PlaywrightConfig`
  excerpt: |
    browser_type: str = "chromium"
    headless: bool = True
    proxy: Optional[Dict[str, str]] = None
    storage_state: Optional[str] = None
    user_data_dir: Optional[str] = None
    channel: Optional[str] = None

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py`
  lines: 41-85
  symbol: `PlaywrightDriver.start`
  excerpt: |
    self._playwright = await async_playwright().start()
    browser_launcher = getattr(self._playwright, self.config.browser_type)
    ...
    self._browser = await browser_launcher.launch(**launch_kwargs)
    self._context = await self._browser.new_context(**context_kwargs)
    self._page = await self._context.new_page()

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/driver_factory.py`
  lines: 35-80
  symbol: `DriverFactory.create`
  excerpt: |
    The factory selects the configured Playwright or Selenium implementation
    and returns it through the AbstractDriver contract.

## Notes

The proposal should separate `connect_over_cdp` configuration from launch-only fields and define ownership of the external Obscura process. A first implementation can keep Obscura process startup outside the Playwright driver and accept an endpoint URL.
