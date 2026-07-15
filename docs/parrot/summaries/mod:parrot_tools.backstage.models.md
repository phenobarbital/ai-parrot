---
type: Wiki Summary
title: parrot_tools.backstage.models
id: mod:parrot_tools.backstage.models
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Pydantic models for Backstage Catalog API responses.
relates_to:
- concept: class:parrot_tools.backstage.models.EntitiesQueryResponse
  rel: defines
- concept: class:parrot_tools.backstage.models.Entity
  rel: defines
- concept: class:parrot_tools.backstage.models.EntityFacet
  rel: defines
- concept: class:parrot_tools.backstage.models.EntityFacetsResponse
  rel: defines
- concept: class:parrot_tools.backstage.models.EntityMeta
  rel: defines
- concept: class:parrot_tools.backstage.models.EntityRelation
  rel: defines
- concept: class:parrot_tools.backstage.models.Location
  rel: defines
- concept: class:parrot_tools.backstage.models.LocationResponse
  rel: defines
---

# `parrot_tools.backstage.models`

Pydantic models for Backstage Catalog API responses.

## Classes

- **`EntityMeta(BaseModel)`** — Backstage entity metadata.
- **`EntityRelation(BaseModel)`** — Relationship between entities.
- **`Entity(BaseModel)`** — Backstage catalog entity.
- **`EntitiesQueryResponse(BaseModel)`** — Paginated entity query response.
- **`EntityFacet(BaseModel)`** — A single facet value with its count.
- **`EntityFacetsResponse(BaseModel)`** — Response from entity-facets endpoint.
- **`Location(BaseModel)`** — Backstage catalog location.
- **`LocationResponse(BaseModel)`** — Response from location registration.
