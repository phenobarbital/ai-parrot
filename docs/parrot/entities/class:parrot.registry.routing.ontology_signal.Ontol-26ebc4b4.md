---
type: Wiki Entity
title: OntologyPreAnnotator
id: class:parrot.registry.routing.ontology_signal.OntologyPreAnnotator
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Adapter that exposes ``OntologyIntentResolver`` as a simple annotator.
---

# OntologyPreAnnotator

Defined in [`parrot.registry.routing.ontology_signal`](../summaries/mod:parrot.registry.routing.ontology_signal.md).

```python
class OntologyPreAnnotator
```

Adapter that exposes ``OntologyIntentResolver`` as a simple annotator.

Args:
    resolver: An ``OntologyIntentResolver`` instance, any object that
        supports ``resolve_intent(query)`` or ``resolve(query)`` (sync or
        async), or ``None`` for a no-op annotator.

## Methods

- `async def annotate(self, query: str) -> dict` — Annotate *query* using the configured resolver.
