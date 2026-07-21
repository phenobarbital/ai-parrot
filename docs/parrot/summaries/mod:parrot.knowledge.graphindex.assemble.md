---
type: Wiki Summary
title: parrot.knowledge.graphindex.assemble
id: mod:parrot.knowledge.graphindex.assemble
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Graph assembly stage for GraphIndex.
relates_to:
- concept: class:parrot.knowledge.graphindex.assemble.GraphAssembler
  rel: defines
- concept: mod:parrot.knowledge.graphindex.schema
  rel: references
---

# `parrot.knowledge.graphindex.assemble`

Graph assembly stage for GraphIndex.

Builds a ``rustworkx.PyDiGraph`` from streams of ``UniversalNode`` and
``UniversalEdge``.  Node payloads are lightweight metadata dicts (IDs, kind,
title, domain_tags); source content is referenced via ``content_ref``, not
stored in the graph.

Per-tenant isolation: each ``GraphAssembler`` instance is scoped to a single
tenant, consistent with ``OntologyGraphStore`` isolation patterns.

## Classes

- **`GraphAssembler`** — Build and query a rustworkx PyDiGraph from UniversalNode/UniversalEdge streams.
