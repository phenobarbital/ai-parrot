---
id: F001
query_id: Q001
type: read
intent: Locate the shared browser driver contract and existing Playwright/Selenium implementations
executed_at: 2026-09-05T13:52:00Z
depth: 0
parent_id: null
---

# F001 — Existing browser abstraction is the primary adapter seam

## Summary

`AbstractDriver` is the shared asynchronous browser contract. It covers lifecycle, navigation, DOM interaction, extraction, waiting, JavaScript evaluation, screenshots, and extended capabilities. `PlaywrightDriver` implements it using Playwright's async API and owns browser/context/page lifecycle, while the repository also contains a Selenium implementation and a factory for selecting a driver.

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py`
  lines: 11-31, 34-180
  symbol: `AbstractDriver`
  excerpt: |
    class AbstractDriver(ABC):
        """Unified interface for browser automation."""
    The contract groups lifecycle, navigation, DOM interaction, extraction,
    waiting, scripts, and extended capabilities.

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py`
  lines: 15-105
  symbol: `PlaywrightDriver.start` and `PlaywrightDriver.quit`
  excerpt: |
    class PlaywrightDriver(AbstractDriver):
        ...
        async def start(self) -> None:
            from playwright.async_api import async_playwright
            ...
            self._browser = await browser_launcher.launch(**launch_kwargs)
        async def quit(self) -> None:
            ...

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/driver_factory.py`
  lines: 1-80
  symbol: `DriverFactory`
  excerpt: |
    DriverFactory is the single entry point for obtaining a configured
    AbstractDriver; PlaywrightDriver and SeleniumDriver are loaded lazily.

## Notes

An Obscura integration should first target this abstraction and preserve the existing toolkit action contract. A CDP-backed Playwright connection may allow reuse of `PlaywrightDriver` with a separate launch/connect mode; a dedicated driver is only needed if Playwright's connection API cannot express the required lifecycle or capabilities.
