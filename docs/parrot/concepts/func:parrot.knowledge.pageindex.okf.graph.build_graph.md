---
type: Concept
title: build_graph()
id: func:parrot.knowledge.pageindex.okf.graph.build_graph
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Build a full knowledge graph including prose link edges.
---

# build_graph

```python
def build_graph(tree: dict[str, Any], content_loader: Callable[[str], Optional[str]]) -> KnowledgeGraph
```

Build a full knowledge graph including prose link edges.

Constructs a ``KnowledgeGraph`` from the tree JSON and then augments it
with prose-link edges extracted from sidecar bodies via ``content_loader``.

Args:
    tree: PageIndex tree dict with ``structure`` list.
    content_loader: Callable mapping ``concept_id -> Optional[str]``.
        Returns sidecar body content or ``None`` if not found.

Returns:
    Fully built ``KnowledgeGraph``.
