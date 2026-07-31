---
type: Wiki Summary
title: parrot.knowledge.ontology.validators
id: mod:parrot.knowledge.ontology.validators
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: AQL security validation for LLM-generated queries.
relates_to:
- concept: func:parrot.knowledge.ontology.validators.validate_aql
  rel: defines
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.knowledge.ontology.exceptions
  rel: references
---

# `parrot.knowledge.ontology.validators`

AQL security validation for LLM-generated queries.

Ensures that dynamic AQL from the intent resolver is read-only,
depth-limited, and does not access system collections or execute JavaScript.

## Functions

- `async def validate_aql(aql: str, max_depth: int | None=None) -> str` — Validate LLM-generated AQL for safety.
