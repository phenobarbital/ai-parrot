---
type: Wiki Entity
title: KnowledgeGraph
id: class:parrot.knowledge.pageindex.okf.graph.KnowledgeGraph
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: In-memory adjacency graph keyed by concept_id.
---

# KnowledgeGraph

Defined in [`parrot.knowledge.pageindex.okf.graph`](../summaries/mod:parrot.knowledge.pageindex.okf.graph.md).

```python
class KnowledgeGraph
```

In-memory adjacency graph keyed by concept_id.

Builds from ``relates_to`` edges in the JSON tree and from markdown
hyperlinks in sidecar bodies (via ``build_graph``).

Broken links (target concept_id unknown) are collected in ``_broken``
but never raise an exception.

Attributes:
    _adj: Adjacency dict ``{source_concept_id: [edge_dict, ...]}``.
    _concepts: Set of all known concept_ids.
    _broken: List of broken edge dicts.

## Methods

- `def add_prose_links(self, concept_id: str, body: str) -> None` — Add prose hyperlink edges from a sidecar body.
- `def neighbors(self, concept_id: str, rel: Optional[str]=None) -> list[dict]` — Return neighbors of a concept, optionally filtered by relation type.
- `def trace(self, concept_id: str, rel_chain: list[str]) -> list[list[str]]` — Multi-hop traversal following a chain of typed relations.
- `def broken_links(self) -> list[dict]` — Return all edges whose target concept_id is unknown.
- `def concepts(self) -> set[str]` — Return the set of all known concept_ids.
