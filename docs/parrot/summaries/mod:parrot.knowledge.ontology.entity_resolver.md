---
type: Wiki Summary
title: parrot.knowledge.ontology.entity_resolver
id: mod:parrot.knowledge.ontology.entity_resolver
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Entity extraction and resolution for the ontology pipeline (FEAT-158).
relates_to:
- concept: class:parrot.knowledge.ontology.entity_resolver.EntityAmbiguityError
  rel: defines
- concept: class:parrot.knowledge.ontology.entity_resolver.EntityNotFoundError
  rel: defines
- concept: class:parrot.knowledge.ontology.entity_resolver.EntityResolver
  rel: defines
- concept: mod:parrot.knowledge.ontology.graph_store
  rel: references
- concept: mod:parrot.knowledge.ontology.schema
  rel: references
---

# `parrot.knowledge.ontology.entity_resolver`

Entity extraction and resolution for the ontology pipeline (FEAT-158).

Converts natural-language entity mentions (e.g., "Jesús") to graph ``_id``s
using one of four pluggable strategies:

- ``exact_id_match``: exact AQL filter on the entity's key field.
- ``fuzzy_name_match``: case-insensitive LIKE filter with AQL.
- ``ai_assisted``: fuzzy shortlist + LLM ranking (requires ``llm_client``).
- ``hybrid_concept_match``: 3-stage cascade (synonym → vector → LLM) with
  multi-concept conjunction parsing (FEAT-159).

Typed exceptions (``EntityAmbiguityError``, ``EntityNotFoundError``) are
raised so the Mixin can translate them to appropriate ``ContextEnvelope`` states.

**Default-deny on ambiguity**: when ``ambiguity_strategy=ask_user`` or ``fail``,
multiple candidates always raise ``EntityAmbiguityError``.

## Classes

- **`EntityAmbiguityError(Exception)`** — Raised when multiple candidates match and the strategy is ``ask_user``
- **`EntityNotFoundError(Exception)`** — Raised when no candidates match a required entity extraction rule.
- **`EntityResolver`** — Extracts named-entity mentions from a query and resolves them to graph
