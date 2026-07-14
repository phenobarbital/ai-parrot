---
type: Wiki Summary
title: parrot_tools.scraping.executor
id: mod:parrot_tools.scraping.executor
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Step Executor — standalone scraping plan execution.
relates_to:
- concept: func:parrot_tools.scraping.executor.execute_plan_steps
  rel: defines
- concept: mod:parrot.utils.jsonld_extractors
  rel: references
- concept: mod:parrot_tools.scraping.advanced_actions
  rel: references
- concept: mod:parrot_tools.scraping.drivers.abstract
  rel: references
- concept: mod:parrot_tools.scraping.models
  rel: references
- concept: mod:parrot_tools.scraping.plan
  rel: references
- concept: mod:parrot_tools.scraping.toolkit_models
  rel: references
---

# `parrot_tools.scraping.executor`

Step Executor — standalone scraping plan execution.

Extracts the step-execution pipeline from ``WebScrapingTool._execute`` into a
reusable async function. Both ``WebScrapingToolkit.scrape()`` and ``CrawlEngine``
can share this execution logic without duplication.

All driver interactions use the ``AbstractDriver`` interface exclusively;
no Selenium-specific imports live in this module.

## Functions

- `async def execute_plan_steps(driver: AbstractDriver, plan: Optional[ScrapingPlan]=None, steps: Optional[List[Dict[str, Any]]]=None, selectors: Optional[List[Dict[str, Any]]]=None, config: Optional[DriverConfig]=None, base_url: Optional[str]=None) -> ScrapingResult` — Execute a scraping plan's steps against a browser driver.
