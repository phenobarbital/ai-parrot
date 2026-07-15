---
type: Wiki Entity
title: ExtractionPlanGenerator
id: class:parrot_tools.scraping.extraction_plan_generator.ExtractionPlanGenerator
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Generates ExtractionPlan from HTML content + objective using LLM reconnaissance.
---

# ExtractionPlanGenerator

Defined in [`parrot_tools.scraping.extraction_plan_generator`](../summaries/mod:parrot_tools.scraping.extraction_plan_generator.md).

```python
class ExtractionPlanGenerator
```

Generates ExtractionPlan from HTML content + objective using LLM reconnaissance.

Makes a single LLM call with a cleaned version of the page HTML and the
extraction objective.  The LLM is prompted to identify entity types and
emit CSS selectors that can be used for mechanical extraction.

The LLM client must support ``async def complete(prompt: str) -> str``.

Args:
    llm_client: Any object with an async ``complete(prompt)`` method.

## Methods

- `async def generate(self, url: str, objective: str, content: str, hints: Optional[Dict[str, Any]]=None, ignore_sections: Optional[List[str]]=None) -> ExtractionPlan` — Generate an ExtractionPlan via LLM reconnaissance.
