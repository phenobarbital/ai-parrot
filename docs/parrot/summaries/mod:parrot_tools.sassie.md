---
type: Wiki Summary
title: parrot_tools.sassie
id: mod:parrot_tools.sassie
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Module parrot_tools.sassie
relates_to:
- concept: class:parrot_tools.sassie.ClientInput
  rel: defines
- concept: class:parrot_tools.sassie.EvaluationRecord
  rel: defines
- concept: class:parrot_tools.sassie.ProductInfo
  rel: defines
- concept: class:parrot_tools.sassie.ProductInput
  rel: defines
- concept: class:parrot_tools.sassie.RetailerEvaluation
  rel: defines
- concept: class:parrot_tools.sassie.RetailerInput
  rel: defines
- concept: class:parrot_tools.sassie.VisitData
  rel: defines
- concept: class:parrot_tools.sassie.VisitDataResponse
  rel: defines
- concept: class:parrot_tools.sassie.VisitsToolkit
  rel: defines
- concept: mod:parrot.exceptions
  rel: references
---

# `parrot_tools.sassie`

## Classes

- **`RetailerInput(BaseModel)`** — Input schema for querying retailer evaluation data.
- **`RetailerEvaluation(BaseModel)`** — Schema for retailer evaluation data.
- **`ProductInput(BaseModel)`** — Input schema for querying Epson product information.
- **`ProductInfo(BaseModel)`** — Schema for the product information returned by the query.
- **`ClientInput(BaseModel)`** — Input schema for client-related tools.
- **`VisitData(BaseModel)`** — Individual visit data entry containing question and answer information.
- **`EvaluationRecord(BaseModel)`** — Complete evaluation record with visit data and metadata.
- **`VisitDataResponse(BaseModel)`** — Simplified model containing only the visit data.
- **`VisitsToolkit(BaseNextStop)`** — Toolkit for managing employee-related operations in Sassie Survey Project.
