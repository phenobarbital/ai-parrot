---
type: Concept
title: validate_aql()
id: func:parrot.knowledge.ontology.validators.validate_aql
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Validate LLM-generated AQL for safety.
---

# validate_aql

```python
async def validate_aql(aql: str, max_depth: int | None=None) -> str
```

Validate LLM-generated AQL for safety.

Checks (in order):
    1. No mutation keywords (INSERT, UPDATE, REMOVE, REPLACE, UPSERT).
    2. No system collection access (_system, _graphs, _modules, etc.).
    3. No inline JavaScript execution (APPLY, CALL, V8).
    4. Traversal depth does not exceed ``max_depth``.

Args:
    aql: The AQL query string to validate.
    max_depth: Maximum allowed traversal depth. If None, uses
        ``ONTOLOGY_MAX_TRAVERSAL_DEPTH`` from conf.

Returns:
    The validated AQL string (unchanged).

Raises:
    AQLValidationError: If any safety check fails, with a message
        indicating which check was violated.
