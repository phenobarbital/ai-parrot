---
type: Wiki Summary
title: parrot_tools.querytoolkit
id: mod:parrot_tools.querytoolkit
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module parrot_tools.querytoolkit
relates_to:
- concept: class:parrot_tools.querytoolkit.QueryToolkit
  rel: defines
- concept: func:parrot_tools.querytoolkit.get_model_from_collection
  rel: defines
- concept: func:parrot_tools.querytoolkit.is_collection_model
  rel: defines
- concept: mod:parrot._imports
  rel: references
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.exceptions
  rel: references
- concept: mod:parrot_tools.toolkit
  rel: references
---

# `parrot_tools.querytoolkit`

## Classes

- **`QueryToolkit(AbstractToolkit)`** — Abstract base class for DB Queries-like Toolkits.

## Functions

- `def is_collection_model(structured_obj: type) -> bool` — Determine if a BaseModel is a collection container (single instance with records field)
- `def get_model_from_collection(collection_model: type) -> type` — Extract the individual record model from a collection container model.
