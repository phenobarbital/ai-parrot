---
type: Wiki Summary
title: parrot.knowledge.ontology.concept_catalog.seed
id: mod:parrot.knowledge.ontology.concept_catalog.seed
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Concept Catalog YAML seed utility (FEAT-159 TASK-1090).
relates_to:
- concept: func:parrot.knowledge.ontology.concept_catalog.seed.seed_concepts_from_yaml
  rel: defines
- concept: mod:parrot.knowledge.ontology.concept_catalog.service
  rel: references
- concept: mod:parrot.knowledge.ontology.exceptions
  rel: references
---

# `parrot.knowledge.ontology.concept_catalog.seed`

Concept Catalog YAML seed utility (FEAT-159 TASK-1090).

Seeds concept rows from an existing YAML ontology file into the Postgres
concept catalog.  The function is idempotent: concepts whose ``(tenant_id,
slug)`` already exist in any state are silently skipped.

Usage (example)::

    import asyncpg
    from parrot.knowledge.ontology.concept_catalog.service import ConceptCatalogService
    from parrot.knowledge.ontology.concept_catalog.seed import seed_concepts_from_yaml

    pool = await asyncpg.create_pool(dsn)
    svc  = ConceptCatalogService(pool)
    seeded = await seed_concepts_from_yaml("my-tenant", Path("base.ontology.yaml"), svc)
    print(f"Seeded {seeded} concepts.")

## Functions

- `async def seed_concepts_from_yaml(tenant_id: str, yaml_path: Path, service: ConceptCatalogService) -> int` — Seed concept rows from a YAML ontology file.
