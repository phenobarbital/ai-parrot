---
type: Wiki Summary
title: parrot.knowledge.ontology.tenant
id: mod:parrot.knowledge.ontology.tenant
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Multi-tenant ontology resolution and caching.
relates_to:
- concept: class:parrot.knowledge.ontology.tenant.TenantOntologyManager
  rel: defines
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.knowledge.ontology.concept_catalog.models
  rel: references
- concept: mod:parrot.knowledge.ontology.concept_catalog.service
  rel: references
- concept: mod:parrot.knowledge.ontology.merger
  rel: references
- concept: mod:parrot.knowledge.ontology.parser
  rel: references
- concept: mod:parrot.knowledge.ontology.schema
  rel: references
- concept: mod:parrot.knowledge.ontology.schema_overlay.models
  rel: references
- concept: mod:parrot.knowledge.ontology.schema_overlay.service
  rel: references
---

# `parrot.knowledge.ontology.tenant`

Multi-tenant ontology resolution and caching.

Resolves the merged ontology for each tenant using the three-layer
YAML chain (base → domain → client) and caches the result in memory.

FEAT-159 (TASK-1098): Extended to compose PG overlay (approved concept rows
and approved schema overlay rows) on top of the YAML chain via the new
async ``resolve_with_overlay()`` method.  The existing synchronous
``resolve()`` is unchanged for backward compatibility.

## Classes

- **`TenantOntologyManager`** — Resolve and cache merged ontology per tenant.
