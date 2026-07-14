---
type: Wiki Entity
title: WebScrapingToolkit
id: class:parrot_tools.scraping.toolkit.WebScrapingToolkit
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Toolkit for intelligent web scraping and crawling with plan caching.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# WebScrapingToolkit

Defined in [`parrot_tools.scraping.toolkit`](../summaries/mod:parrot_tools.scraping.toolkit.md).

```python
class WebScrapingToolkit(AbstractToolkit)
```

Toolkit for intelligent web scraping and crawling with plan caching.

Inherits from ``AbstractToolkit`` so that every public async method is
auto-discovered as a tool.  Coordinates plan inference (LLM), single-page
scraping, multi-page crawling, and plan persistence.

Args:
    driver_type: Browser driver backend to use.
    browser: Browser to launch.
    headless: Run headless.
    session_based: Reuse driver across calls (sequential only).
    mobile: Enable mobile emulation.
    mobile_device: Specific mobile device name.
    auto_install: Auto-install/update browser driver.
    default_timeout: Default timeout in seconds.
    retry_attempts: Retries for failed operations.
    delay_between_actions: Seconds between plan steps.
    overlay_housekeeping: Dismiss overlays between actions.
    disable_images: Block image loading.
    custom_user_agent: Override user agent.
    plans_dir: Root directory for plan storage.
    llm_client: LLM client with ``async complete(prompt) -> str``.
    **kwargs: Passed through to ``AbstractToolkit``.

## Methods

- `async def start(self) -> None` — Initialise session driver when ``session_based=True``.
- `async def stop(self) -> None` — Shut down the session driver if active.
- `async def plan_create(self, url: str, objective: str, hints: Optional[Dict[str, Any]]=None, force_regenerate: bool=False, snapshot: Optional[PageSnapshot]=None, auto_snapshot: bool=True) -> ScrapingPlan` — Create a scraping plan for a URL via LLM or cache.
- `async def plan_save(self, plan: ScrapingPlan, overwrite: bool=False) -> PlanSaveResult` — Save a scraping plan to disk and register it.
- `async def plan_load(self, url_or_name: str) -> Optional[ScrapingPlan]` — Load a plan by URL (registry lookup) or by name.
- `async def plan_list(self, domain_filter: Optional[str]=None, tag_filter: Optional[str]=None) -> List[PlanSummary]` — List registered plans with optional filtering.
- `async def plan_delete(self, name: str, delete_file: bool=True) -> bool` — Delete a plan from the registry and optionally from disk.
- `async def scrape(self, url: str, plan: Optional[Union[ScrapingPlan, Dict[str, Any]]]=None, objective: Optional[str]=None, steps: Optional[List[Dict[str, Any]]]=None, selectors: Optional[List[Dict[str, Any]]]=None, save_plan: bool=False, browser_config_override: Optional[Dict[str, Any]]=None, max_refinement_attempts: int=1) -> ScrapingResult` — Scrape a single page using a plan, raw steps, or auto-generation.
- `async def crawl(self, start_url: str, depth: int=1, max_pages: Optional[int]=None, follow_selector: Optional[str]=None, follow_pattern: Optional[str]=None, plan: Optional[Union[ScrapingPlan, Dict[str, Any]]]=None, objective: Optional[str]=None, save_plan: bool=False, concurrency: int=1) -> Any` — Crawl multiple pages starting from a URL.
