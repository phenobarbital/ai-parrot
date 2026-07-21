---
type: Wiki Entity
title: WeeklySecuritySummarizer
id: class:parrot_tools.security.summarizer.WeeklySecuritySummarizer
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Produces a ``WeeklySummary`` from a list of scan ``ReportRef``s.
---

# WeeklySecuritySummarizer

Defined in [`parrot_tools.security.summarizer`](../summaries/mod:parrot_tools.security.summarizer.md).

```python
class WeeklySecuritySummarizer
```

Produces a ``WeeklySummary`` from a list of scan ``ReportRef``s.

All severity arithmetic is deterministic Python — the LLM is invoked
EXACTLY ONCE per ``build()`` call, solely to generate the
``executive_paragraph``.

Args:
    llm_client: Any LLM client that exposes an async ``ask()`` method
        accepting ``prompt: str`` and ``structured_output: type``, and
        returns an object with a ``structured_output`` attribute containing
        the parsed Pydantic model.  The ``GoogleGenAIClient`` satisfies
        this contract.

## Methods

- `async def build(self, scans: list[ReportRef], framework: str, provider: str, previous_summary_data: WeeklySummary | None=None) -> WeeklySummary` — Build a ``WeeklySummary`` for the given scan refs.
