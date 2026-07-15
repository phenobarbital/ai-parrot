---
type: Concept
title: validate_envelope()
id: func:parrot.outputs.a2ui.catalog.validate_envelope
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Validate an envelope against the catalog allowlist and the action gate.
---

# validate_envelope

```python
def validate_envelope(envelope: CreateSurface, *, origin: ProducerOrigin=ProducerOrigin.TOOL) -> None
```

Validate an envelope against the catalog allowlist and the action gate.

Walks the envelope's top-level component adjacency list AND every nested
composite child descriptor. Reports ALL problems (not just the first) so
Module 9's retry loop can re-prompt with full error context.

Args:
    envelope: The :class:`CreateSurface` envelope to validate.
    origin: Producer origin. ``requires_actions`` rejection applies ONLY to
        :attr:`ProducerOrigin.LLM` envelopes.

Raises:
    CatalogValidationError: If any component (top-level or nested) is unknown,
        or (for LLM origin) any component is action-bearing.
