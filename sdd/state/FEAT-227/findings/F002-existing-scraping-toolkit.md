---
id: F002
query_id: Q002
type: read
intent: Understand existing WebScrapingToolkit and Playwright integration in AI-Parrot
executed_at: 2026-06-05T00:00:00Z
duration_ms: 2500
parent_id: null
depth: 0
---

# F002 — Existing WebScrapingToolkit and Playwright infrastructure

## Summary

AI-Parrot has a production-grade WebScrapingToolkit (AbstractToolkit subclass) at
`packages/ai-parrot-tools/src/parrot_tools/scraping/`. It includes a full Playwright
driver (async_api), abstract driver interface, plan-based execution, LLM-driven plan
generation, and extraction scoring with refinement loops. The PlaywrightDriver supports
screenshot, click, fill, hover, type, scroll, PDF export, HAR recording, tracing, and
session persistence. The driver uses async Playwright (playwright.async_api) which aligns
with AI-Parrot's async-first architecture.

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py`
  lines: 274-342
  symbol: `WebScrapingToolkit(AbstractToolkit)`
  excerpt: |
    class WebScrapingToolkit(AbstractToolkit):
        def __init__(self, driver_type="selenium", browser="chrome",
                     headless=True, session_based=False, ...):
    # 7 tool methods: plan_create, plan_save, plan_load, plan_list,
    # plan_delete, scrape, crawl

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py`
  lines: 11-352
  symbol: `AbstractDriver`
  excerpt: |
    # Methods: start(), quit(), navigate(), click(), fill(), select_option(),
    # hover(), press_key(), get_page_source(), get_text(), screenshot(),
    # wait_for_selector(), execute_script(), intercept_requests(), etc.

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py`
  lines: 1-395
  symbol: `PlaywrightDriver`
  excerpt: |
    # Full async implementation using playwright.async_api
    # Supports: intercept_requests, record_har, save_pdf,
    # start_tracing, save_storage_state, new_page, get_network_responses

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_config.py`
  lines: 9-71
  symbol: `PlaywrightConfig`
  excerpt: |
    @dataclass
    class PlaywrightConfig:
        browser_type: str = "chromium"
        headless: bool = True
        viewport: Optional[Dict[str, int]] = None
        mobile: bool = False
        device_name: Optional[str] = None

## Notes

- WebScrapingToolkit uses CSS selectors and XPath for element targeting
- Computer-Use model uses coordinate-based (x,y pixel) targeting — fundamentally different
- Existing toolkit is plan-based (LLM generates selector plans); Computer-Use is vision-based
- Both can coexist: ComputerInteraction for vision-driven tasks, WebScraping for selector-driven
- PlaywrightDriver (async) can be reused/wrapped for ComputerInteraction's browser backend
