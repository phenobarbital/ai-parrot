---
type: Wiki Summary
title: parrot.knowledge.pageindex.okf.tools
id: mod:parrot.knowledge.pageindex.okf.tools
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Named read tools for OKF knowledge-layer retrieval and traversal.
relates_to:
- concept: class:parrot.knowledge.pageindex.okf.tools.OKFToolkit
  rel: defines
- concept: mod:parrot.knowledge.pageindex.content_store
  rel: references
- concept: mod:parrot.knowledge.pageindex.okf.bundle
  rel: references
- concept: mod:parrot.knowledge.pageindex.okf.graph
  rel: references
- concept: mod:parrot.knowledge.pageindex.okf.lint
  rel: references
- concept: mod:parrot.knowledge.pageindex.okf.ontology
  rel: references
- concept: mod:parrot.knowledge.pageindex.okf.projection
  rel: references
- concept: mod:parrot.knowledge.pageindex.store
  rel: references
- concept: mod:parrot.knowledge.pageindex.utils
  rel: references
- concept: mod:parrot.tools
  rel: references
---

# `parrot.knowledge.pageindex.okf.tools`

Named read tools for OKF knowledge-layer retrieval and traversal.

Provides **separate named tools** (spec constraint — no branching search)
for type-scoped retrieval and multi-hop compliance traversal:

- ``find_by_type``: Exact type pre-filter then search over nodes.
- ``list_concepts``: Browse ToC, optionally filtered by type.
- ``get_concept``: Retrieve frontmatter + body for a stable concept_id.
- ``get_related``: In-memory graph traversal, optional rel filter.
- ``trace_mapping``: Multi-hop typed-chain traversal.
- ``cite``: Per-node provenance (document, pages, URL).
- ``lint_knowledge_base``: Run lint checks; returns structured LintReport dict.
- ``export_okf_bundle``: Export tree as OKF v0.1 bundle directory.
- ``import_okf_bundle``: Import OKF bundle directory into tree.

Each tool is a ``@tool``-decorated function wrapped in ``OKFToolkit``, which
holds the shared state (tree dict, graph, content_store).

Design notes (spec §2.5, §3 Module 7):
- **Deterministic gate before probabilistic ranker**: ``find_by_type`` filters
  candidates by ``type`` *exactly* before any ranking.
- **Type/rel filters are a guide, not a contract**: access restriction for
  sensitive types lives in the execution layer (PBAC), not here.
- **Separate named tools**: each is its own ``@tool``-decorated function.
  No branching ``search(type=...)`` multi-purpose tool.

## Classes

- **`OKFToolkit`** — Stateful container for OKF read tools.
