---
type: Wiki Entity
title: PlanGenerator
id: class:parrot_tools.scraping.plan_generator.PlanGenerator
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Generates ScrapingPlan from URL + objective using an LLM client.
---

# PlanGenerator

Defined in [`parrot_tools.scraping.plan_generator`](../summaries/mod:parrot_tools.scraping.plan_generator.md).

```python
class PlanGenerator
```

Generates ScrapingPlan from URL + objective using an LLM client.

The LLM client must support ``async def complete(prompt: str) -> str``.

Args:
    llm_client: Any object with an async ``complete(prompt)`` method.

## Methods

- `async def generate(self, url: str, objective: str, snapshot: Optional[PageSnapshot]=None, hints: Optional[Dict[str, Any]]=None, auto_snapshot: bool=True, snapshot_fetcher: Optional[Callable[[str], Any]]=None) -> ScrapingPlan` — Generate a scraping plan via LLM inference.
- `async def refine(self, url: str, objective: str, prior_plan: ScrapingPlan, extraction_summary: str, step_errors: str, diagnosis: str, snapshot: Optional[PageSnapshot]=None) -> ScrapingPlan` — Regenerate a plan given the failure signals from a prior run.
