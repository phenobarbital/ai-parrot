---
type: Wiki Summary
title: parrot.knowledge.ontology.schema_overlay
id: mod:parrot.knowledge.ontology.schema_overlay
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Schema Overlay sub-package for FEAT-159 Topic-Authority Ontology Curation.
relates_to:
- concept: mod:parrot.knowledge.ontology
  rel: references
---

# `parrot.knowledge.ontology.schema_overlay`

Schema Overlay sub-package for FEAT-159 Topic-Authority Ontology Curation.

Provides Pydantic models, validator, service, worker, and HTTP modules for
managing per-tenant schema overlays (entity types, relation types, traversal
patterns) in Postgres with a mandatory dry-run gate before approval.
