---
type: Wiki Entity
title: ExtractionResult
id: class:parrot_tools.scraping.extraction_models.ExtractionResult
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Complete result from an extraction run.
---

# ExtractionResult

Defined in [`parrot_tools.scraping.extraction_models`](../summaries/mod:parrot_tools.scraping.extraction_models.md).

```python
class ExtractionResult(BaseModel)
```

Complete result from an extraction run.

Args:
    url: Target URL that was scraped.
    objective: Extraction goal.
    entities: All entities extracted from the page.
    plan_used: The ExtractionPlan that governed extraction.
    extraction_strategy: Strategy used (hybrid, selector, llm).
    success: Whether the extraction succeeded.
    error_message: Error details if ``success`` is False.
    elapsed_seconds: Wall-clock time for the extraction run.

## Methods

- `def total_entities(self) -> int` — Total number of entities extracted (computed from ``entities`` list).
