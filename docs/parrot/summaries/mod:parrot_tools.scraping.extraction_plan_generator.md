---
type: Wiki Summary
title: parrot_tools.scraping.extraction_plan_generator
id: mod:parrot_tools.scraping.extraction_plan_generator
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: ExtractionPlanGenerator — LLM-based ExtractionPlan generation.
relates_to:
- concept: class:parrot_tools.scraping.extraction_plan_generator.ExtractionPlanGenerator
  rel: defines
- concept: mod:parrot_tools.scraping.extraction_models
  rel: references
- concept: mod:parrot_tools.scraping.plan_generator
  rel: references
---

# `parrot_tools.scraping.extraction_plan_generator`

ExtractionPlanGenerator — LLM-based ExtractionPlan generation.

Analyzes raw HTML content and a natural language objective to produce an
``ExtractionPlan`` via a single LLM recon call.  The resulting plan
specifies entity types, fields, and CSS selectors derived from the page
structure.

## Classes

- **`ExtractionPlanGenerator`** — Generates ExtractionPlan from HTML content + objective using LLM reconnaissance.
