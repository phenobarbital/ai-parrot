---
type: Wiki Entity
title: MonthlySecuritySummarizer
id: class:parrot_tools.security.summarizer.MonthlySecuritySummarizer
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Produces a ``MonthlySummary`` from a list of weekly ``WeeklySummary`` objects.
---

# MonthlySecuritySummarizer

Defined in [`parrot_tools.security.summarizer`](../summaries/mod:parrot_tools.security.summarizer.md).

```python
class MonthlySecuritySummarizer
```

Produces a ``MonthlySummary`` from a list of weekly ``WeeklySummary`` objects.

Diff math operates on the ``persistent_findings`` sets of each weekly
summary.  The LLM is invoked EXACTLY ONCE per ``build()`` call, solely
for the ``executive_paragraph``.

Args:
    llm_client: Any LLM client satisfying the same contract as
        ``WeeklySecuritySummarizer``.

## Methods

- `async def build(self, weekly_summaries: list[WeeklySummary], framework: str, provider: str) -> MonthlySummary` — Build a ``MonthlySummary`` from a list of weekly summaries.
