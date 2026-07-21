---
type: Wiki Summary
title: parrot.knowledge.graphindex
id: mod:parrot.knowledge.graphindex
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: GraphIndex — Structured Knowledge Graph Indexing for AI-Parrot.
relates_to:
- concept: mod:parrot.knowledge.graphindex.communities
  rel: references
- concept: mod:parrot.knowledge.graphindex.export_html
  rel: references
- concept: mod:parrot.knowledge.graphindex.extractors.odoo_code
  rel: references
- concept: mod:parrot.knowledge.graphindex.persist_sqlite
  rel: references
- concept: mod:parrot.knowledge.graphindex.projection
  rel: references
- concept: mod:parrot.knowledge.graphindex.schema
  rel: references
- concept: mod:parrot.knowledge.graphindex.signals
  rel: references
- concept: mod:parrot.knowledge.graphindex.sqlite_reader
  rel: references
---

# `parrot.knowledge.graphindex`

GraphIndex — Structured Knowledge Graph Indexing for AI-Parrot.

This package provides a unified knowledge graph that spans code, documents,
and skills within a single tenant. It is organized as a 6-stage pipeline:

1. Extract  — Code, Loader, and SKILL.md extractors emit UniversalNode/UniversalEdge
2. Embed    — Batch embedding via EmbeddingModel → FAISS (hot) + pgvector (persistent)
3. Assemble — rustworkx PyDiGraph built in-process from node/edge streams
4. Resolve  — Level 1 cosine-similarity cross-domain edge inference
5. Persist  — OntologyGraphStore → ArangoDB + embeddings → pgvector
6. Analyze  — Centrality, surprising connections, GRAPH_REPORT.md generation

The agent-facing toolkit lives in ``parrot_tools.graphindex.toolkit``.
