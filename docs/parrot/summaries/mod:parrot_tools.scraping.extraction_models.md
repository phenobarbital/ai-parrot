---
type: Wiki Summary
title: parrot_tools.scraping.extraction_models
id: mod:parrot_tools.scraping.extraction_models
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: ExtractionPlan Data Models.
relates_to:
- concept: class:parrot_tools.scraping.extraction_models.EntityFieldSpec
  rel: defines
- concept: class:parrot_tools.scraping.extraction_models.EntitySpec
  rel: defines
- concept: class:parrot_tools.scraping.extraction_models.ExtractedEntity
  rel: defines
- concept: class:parrot_tools.scraping.extraction_models.ExtractionPlan
  rel: defines
- concept: class:parrot_tools.scraping.extraction_models.ExtractionResult
  rel: defines
- concept: mod:parrot_tools.scraping.plan
  rel: references
---

# `parrot_tools.scraping.extraction_models`

ExtractionPlan Data Models.

Pydantic v2 models for schema-driven extraction: what to extract (entities,
fields, selectors) and result containers for extracted data.

ExtractionPlan is a richer cousin of ScrapingPlan — it describes WHAT to
extract (entity types, field specs) rather than HOW to navigate (steps).

## Classes

- **`EntityFieldSpec(BaseModel)`** — Specification for a single field within an entity.
- **`EntitySpec(BaseModel)`** — Specification for one type of entity to extract.
- **`ExtractionPlan(BaseModel)`** — Rich schema describing WHAT to extract — translates to ScrapingPlan for execution.
- **`ExtractedEntity(BaseModel)`** — A single structured entity extracted from a page.
- **`ExtractionResult(BaseModel)`** — Complete result from an extraction run.
