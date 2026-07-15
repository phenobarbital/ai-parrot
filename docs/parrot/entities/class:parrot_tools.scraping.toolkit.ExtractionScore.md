---
type: Wiki Entity
title: ExtractionScore
id: class:parrot_tools.scraping.toolkit.ExtractionScore
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Heuristic quality score for a ``ScrapingResult``.
---

# ExtractionScore

Defined in [`parrot_tools.scraping.toolkit`](../summaries/mod:parrot_tools.scraping.toolkit.md).

```python
class ExtractionScore
```

Heuristic quality score for a ``ScrapingResult``.

Attributes:
    value: 0.0 = nothing useful came out, 1.0 = every extract name
        has rows with fully-populated fields.
    reasons: Human-readable diagnostic lines (empty rows, null-field
        rates, step errors). Passed verbatim into the refinement
        prompt so the LLM knows exactly what to fix.
    needs_refinement: True if the result is weak enough that a
        second LLM pass is likely to improve it.

## Methods

- `def summary(self) -> str`
