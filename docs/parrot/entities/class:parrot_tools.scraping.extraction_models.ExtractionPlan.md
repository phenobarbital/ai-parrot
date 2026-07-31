---
type: Wiki Entity
title: ExtractionPlan
id: class:parrot_tools.scraping.extraction_models.ExtractionPlan
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Rich schema describing WHAT to extract — translates to ScrapingPlan for execution.
---

# ExtractionPlan

Defined in [`parrot_tools.scraping.extraction_models`](../summaries/mod:parrot_tools.scraping.extraction_models.md).

```python
class ExtractionPlan(BaseModel)
```

Rich schema describing WHAT to extract — translates to ScrapingPlan for execution.

Auto-populates ``domain``, ``name``, ``fingerprint``, and ``created_at``
from the URL in ``model_post_init``, matching the behaviour of
``ScrapingPlan``.

Args:
    name: Human-readable plan name; auto-derived from domain if not given.
    url: Target URL for extraction.
    domain: Netloc of the target URL; auto-populated from ``url``.
    objective: Natural language description of extraction goal.
    fingerprint: 16-char SHA-256 prefix of the normalised URL; auto-computed.
    entities: Entity type specs defining what to extract.
    ignore_sections: CSS selectors for page sections to strip before
        extraction (e.g. ``nav``, ``footer``, ``.advertisement``).
    page_category: Descriptive category label (e.g.
        ``telecom_prepaid_plans``).
    extraction_strategy: How to extract: ``hybrid``, ``selector``, or
        ``llm``.
    source: Origin of the plan: ``llm``, ``developer``, or ``user``.
    version: Numeric plan version, incremented on updates.
    confidence: LLM confidence score (0.0–1.0) when source is ``llm``.
    created_at: UTC datetime of plan creation; auto-populated if not given.
    last_used_at: UTC datetime of last use.
    success_count: Cumulative successful extraction count.
    failure_count: Cumulative failed extraction count.

## Methods

- `def model_post_init(self, __context: Any) -> None` — Auto-populate domain, name, fingerprint, and created_at from URL.
- `def to_scraping_plan(self) -> ScrapingPlan` — Translate entity/field specs into a ScrapingPlan for mechanical execution.
