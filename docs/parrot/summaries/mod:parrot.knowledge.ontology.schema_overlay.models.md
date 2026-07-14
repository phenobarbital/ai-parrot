---
type: Wiki Summary
title: parrot.knowledge.ontology.schema_overlay.models
id: mod:parrot.knowledge.ontology.schema_overlay.models
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Pydantic v2 row models for the Schema Overlay tables.
relates_to:
- concept: class:parrot.knowledge.ontology.schema_overlay.models.DryRunCheck
  rel: defines
- concept: class:parrot.knowledge.ontology.schema_overlay.models.DryRunReport
  rel: defines
- concept: class:parrot.knowledge.ontology.schema_overlay.models.SchemaOverlayRow
  rel: defines
---

# `parrot.knowledge.ontology.schema_overlay.models`

Pydantic v2 row models for the Schema Overlay tables.

These models represent the Postgres rows for ontology_schema_overlay and
the DryRunReport structure returned by the schema overlay validator.
They are used by the service, validator, worker, and HTTP modules.

## Classes

- **`SchemaOverlayRow(BaseModel)`** — Represents a row in the ontology_schema_overlay Postgres table.
- **`DryRunCheck(BaseModel)`** — Result of a single validation step within a dry-run.
- **`DryRunReport(BaseModel)`** — Result of a schema overlay dry-run validation.
