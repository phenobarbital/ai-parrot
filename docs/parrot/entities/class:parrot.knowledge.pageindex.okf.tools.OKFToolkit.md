---
type: Wiki Entity
title: OKFToolkit
id: class:parrot.knowledge.pageindex.okf.tools.OKFToolkit
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Stateful container for OKF read tools.
---

# OKFToolkit

Defined in [`parrot.knowledge.pageindex.okf.tools`](../summaries/mod:parrot.knowledge.pageindex.okf.tools.md).

```python
class OKFToolkit
```

Stateful container for OKF read tools.

Holds shared state (tree, graph, content_store) and exposes ``@tool``
decorated methods callable by agents.

NOTE: This class intentionally does NOT inherit ``AbstractToolkit``.
OKF tools are read-only, stateless w.r.t. sensitive mutations, and
currently have no HITL confirmation or PBAC permission requirements.
If ``Evidence``-type access control (spec §2.5 "sensitive-type gate")
is enforced in a future pass, migrate this to ``AbstractToolkit`` so
the execution-layer hooks fire correctly.

Args:
    tree: OKF-enriched PageIndex tree dict.
    graph: Pre-built ``KnowledgeGraph`` instance.
    content_store: ``NodeContentStore`` for loading sidecar bodies.
    tree_name: PageIndex tree name (for concept_id lookup).

## Methods

- `def get_tools(self) -> list` — Return all OKF tool callables.
- `def find_by_type(self, concept_type: ConceptType, query: str) -> list[dict]` — Search for concepts of a specific type.
- `def list_concepts(self, concept_type: Optional[ConceptType]=None) -> list[dict]` — Browse the knowledge ToC, optionally filtered by type.
- `def get_concept(self, concept_id: str) -> dict` — Retrieve the self-describing unit for a concept.
- `def get_related(self, concept_id: str, rel: Optional[str]=None) -> list[dict]` — Return in-memory graph neighbors of a concept.
- `def trace_mapping(self, concept_id: str, rel_chain: Optional[list[str]]=None) -> list[list[str]]` — Follow a multi-hop typed chain from a concept.
- `def cite(self, concept_id: str) -> dict` — Return per-node provenance for a concept.
- `def lint_knowledge_base(self, stale_days: int=90) -> dict` — Run lint checks on this knowledge base.
- `def export_okf_bundle(self, output_dir: str) -> dict` — Export this knowledge base as an OKF v0.1 bundle.
- `def import_okf_bundle(self, input_dir: str) -> dict` — Import an OKF bundle directory into a new PageIndex tree.
