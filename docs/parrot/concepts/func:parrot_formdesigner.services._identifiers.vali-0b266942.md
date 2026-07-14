---
type: Concept
title: validate_identifier()
id: func:parrot_formdesigner.services._identifiers.validate_identifier
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Return ``value`` if it is a safe Postgres identifier.
---

# validate_identifier

```python
def validate_identifier(value: str, *, kind: str='identifier') -> str
```

Return ``value`` if it is a safe Postgres identifier.

Args:
    value: Candidate identifier (schema, table, tenant slug, etc.).
    kind: Human-readable label used in the error message.

Returns:
    The validated identifier (unchanged).

Raises:
    ValueError: If ``value`` is not a string matching the whitelist.
