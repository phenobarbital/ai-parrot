---
type: Wiki Summary
title: parrot.knowledge.pageindex.okf.graph
id: mod:parrot.knowledge.pageindex.okf.graph
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: In-memory knowledge graph for OKF concept-level traversal.
relates_to:
- concept: class:parrot.knowledge.pageindex.okf.graph.KnowledgeGraph
  rel: defines
- concept: func:parrot.knowledge.pageindex.okf.graph.build_graph
  rel: defines
- concept: func:parrot.knowledge.pageindex.okf.graph.parse_markdown_links
  rel: defines
- concept: mod:parrot.knowledge.pageindex.okf.ontology
  rel: references
- concept: mod:parrot.knowledge.pageindex.okf.projection
  rel: references
- concept: mod:parrot.knowledge.pageindex.utils
  rel: references
---

# `parrot.knowledge.pageindex.okf.graph`

In-memory knowledge graph for OKF concept-level traversal.

Builds an adjacency structure keyed by ``concept_id`` from two sources:

1. **Typed ``relates_to`` edges** in the authoritative JSON (gold edges).
2. **Untyped prose markdown hyperlinks** parsed from sidecar bodies (noise
   edges with ``rel: references``).

The graph is built at load time and held in memory — there is no ArangoDB
dependency (D4; phase-2 persistence is separate).  Broken links (targets that
are not known concept_ids) are **tolerated and collected** for lint, never
fatal (OKF §5.3/§9).

Design notes:
- Multi-hop traversal via ``trace()`` follows a chain of typed relation types,
  e.g.  ``[maps_to, satisfied_by]``.
- ``parse_markdown_links`` skips fenced code blocks (` ``` `).
- ``build_graph`` is a convenience factory that loads bodies via a callable
  and constructs the full graph.

## Classes

- **`KnowledgeGraph`** — In-memory adjacency graph keyed by concept_id.

## Functions

- `def parse_markdown_links(body: str) -> list[str]` — Extract markdown hyperlink targets from body text.
- `def build_graph(tree: dict[str, Any], content_loader: Callable[[str], Optional[str]]) -> KnowledgeGraph` — Build a full knowledge graph including prose link edges.
