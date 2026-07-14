---
type: Wiki Entity
title: RecallProcessor
id: class:parrot_tools.scraping.recall_processor.RecallProcessor
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Post-extraction LLM recall for rag_text generation and gap-filling.
---

# RecallProcessor

Defined in [`parrot_tools.scraping.recall_processor`](../summaries/mod:parrot_tools.scraping.recall_processor.md).

```python
class RecallProcessor
```

Post-extraction LLM recall for rag_text generation and gap-filling.

Makes a single LLM call after mechanical extraction to:
1. Generate natural language rag_text for each entity
2. Fill missing field values from original page content
3. Flag potentially missed entities (logged at WARNING level)

If the LLM call or response parsing fails, the original entities are
returned unchanged so the pipeline can continue gracefully.

The LLM client must support ``async def complete(prompt: str) -> str``.

Args:
    llm_client: Any object with an async ``complete(prompt)`` method.

## Methods

- `async def recall(self, entities: List[ExtractedEntity], page_html: str, extraction_plan: ExtractionPlan, url: str) -> List[ExtractedEntity]` — Enrich extracted entities with rag_text and gap-filling.
