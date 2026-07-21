---
type: Concept
title: execute_plan_steps()
id: func:parrot_tools.scraping.executor.execute_plan_steps
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Execute a scraping plan's steps against a browser driver.
---

# execute_plan_steps

```python
async def execute_plan_steps(driver: AbstractDriver, plan: Optional[ScrapingPlan]=None, steps: Optional[List[Dict[str, Any]]]=None, selectors: Optional[List[Dict[str, Any]]]=None, config: Optional[DriverConfig]=None, base_url: Optional[str]=None) -> ScrapingResult
```

Execute a scraping plan's steps against a browser driver.

Accepts either a full ``ScrapingPlan`` or a raw ``steps`` list for ad-hoc
usage.  Steps are executed sequentially; selectors are applied after all
steps complete.

Args:
    driver: Browser driver instance implementing ``AbstractDriver``.
    plan: Full ``ScrapingPlan`` (takes priority if provided).
    steps: Raw steps list for ad-hoc usage (used when *plan* is ``None``).
    selectors: Content extraction selectors (used when *plan* is ``None``).
    config: Driver configuration for delay/timeout settings.
    base_url: Fallback base URL for relative link resolution.

Returns:
    ``ScrapingResult`` with extracted data and metadata.
