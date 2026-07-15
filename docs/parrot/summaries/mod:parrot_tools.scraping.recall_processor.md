---
type: Wiki Summary
title: parrot_tools.scraping.recall_processor
id: mod:parrot_tools.scraping.recall_processor
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: RecallProcessor — Post-extraction LLM recall for rag_text generation and
  gap-filling.
relates_to:
- concept: class:parrot_tools.scraping.recall_processor.RecallProcessor
  rel: defines
- concept: mod:parrot_tools.scraping.extraction_models
  rel: references
- concept: mod:parrot_tools.scraping.plan_generator
  rel: references
---

# `parrot_tools.scraping.recall_processor`

RecallProcessor — Post-extraction LLM recall for rag_text generation and gap-filling.

After mechanical extraction has produced a list of ``ExtractedEntity`` objects,
RecallProcessor makes a single LLM call to:
  1. Generate natural language ``rag_text`` for each entity
  2. Fill missing field values from original page content
  3. (Optionally flag potentially missed entities — logged, not surfaced)

## Classes

- **`RecallProcessor`** — Post-extraction LLM recall for rag_text generation and gap-filling.
