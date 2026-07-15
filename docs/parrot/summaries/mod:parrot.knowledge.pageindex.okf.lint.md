---
type: Wiki Summary
title: parrot.knowledge.pageindex.okf.lint
id: mod:parrot.knowledge.pageindex.okf.lint
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Knowledge base lint engine for OKF.
relates_to:
- concept: class:parrot.knowledge.pageindex.okf.lint.LintFinding
  rel: defines
- concept: class:parrot.knowledge.pageindex.okf.lint.LintReport
  rel: defines
- concept: func:parrot.knowledge.pageindex.okf.lint.lint_knowledge_base
  rel: defines
- concept: mod:parrot.knowledge.pageindex.content_store
  rel: references
- concept: mod:parrot.knowledge.pageindex.okf.graph
  rel: references
- concept: mod:parrot.knowledge.pageindex.okf.projection
  rel: references
- concept: mod:parrot.knowledge.pageindex.utils
  rel: references
---

# `parrot.knowledge.pageindex.okf.lint`

Knowledge base lint engine for OKF.

Provides :func:`lint_knowledge_base` which runs four categories of checks on
a PageIndex tree and its in-memory knowledge graph:

1. **Orphan detection** — concepts with zero inbound edges are flagged as
   ``"warning"`` because they may be dead-end nodes that nobody references.
2. **Broken link audit** — edges whose target ``concept_id`` is unknown in the
   graph are flagged as ``"error"`` (surfaced from
   ``KnowledgeGraph.broken_links()``).
3. **Missing concept pages** — concepts that are referenced in ``relates_to``
   but have no sidecar body in ``NodeContentStore`` are flagged as
   ``"warning"``.
4. **Stale claims** — nodes whose frontmatter ``timestamp`` is older than
   ``stale_days`` (default 90) are flagged as ``"warning"``.

Design notes:
- Pure function — no side effects, no mutations to the graph or stores.
- Uses only the public API of :class:`KnowledgeGraph` except for computing
  inbound edge counts, which requires iterating ``neighbors()`` for every
  known concept.
- Broken-link and missing-concept checks are complementary: broken links
  identify edges to *unknown* concept_ids; missing pages identify edges to
  *known* concept_ids that have no stored body.

## Classes

- **`LintFinding(BaseModel)`** — A single lint finding.
- **`LintReport(BaseModel)`** — Structured knowledge base lint report.

## Functions

- `def lint_knowledge_base(graph: KnowledgeGraph, tree: dict, content_store: NodeContentStore, stale_days: int=90) -> LintReport` — Run lint checks on a knowledge base and return a structured report.
