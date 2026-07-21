---
type: Wiki Summary
title: parrot.knowledge.pageindex.toolkit
id: mod:parrot.knowledge.pageindex.toolkit
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Agent-facing toolkit for PageIndex.
relates_to:
- concept: class:parrot.knowledge.pageindex.toolkit.PageIndexToolkit
  rel: defines
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.embeddings.registry
  rel: references
- concept: mod:parrot.knowledge.pageindex
  rel: references
- concept: mod:parrot.knowledge.pageindex.content_store
  rel: references
- concept: mod:parrot.knowledge.pageindex.embedding_store
  rel: references
- concept: mod:parrot.knowledge.pageindex.hybrid_search
  rel: references
- concept: mod:parrot.knowledge.pageindex.ingest
  rel: references
- concept: mod:parrot.knowledge.pageindex.llm_adapter
  rel: references
- concept: mod:parrot.knowledge.pageindex.okf.migrate
  rel: references
- concept: mod:parrot.knowledge.pageindex.okf.ontology
  rel: references
- concept: mod:parrot.knowledge.pageindex.okf.projection
  rel: references
- concept: mod:parrot.knowledge.pageindex.retriever
  rel: references
- concept: mod:parrot.knowledge.pageindex.store
  rel: references
- concept: mod:parrot.knowledge.pageindex.tree_ops
  rel: references
- concept: mod:parrot.knowledge.pageindex.utils
  rel: references
- concept: mod:parrot.tools.toolkit
  rel: references
---

# `parrot.knowledge.pageindex.toolkit`

Agent-facing toolkit for PageIndex.

This toolkit lets an Agent manage one or more named PageIndex trees:
search them (hybrid BM25 + LLM-walk), retrieve aggregated text,
insert new pages from raw content (Two-Step Chain-of-Thought ingest),
and import whole folders preserving directory structure.

Per-tree storage is split into two artefacts:

    <storage_dir>/<tree_name>.json   — lean ToC tree (titles, summaries,
                                       categories, metadata)
    <storage_dir>/<tree_name>/       — sidecar markdown, one .md per node,
                                       served by NodeContentStore

This matches the upstream PageIndex contract: vectorless retrieval over
a hierarchical index, with bodies fetched on demand by node_id.

## Classes

- **`PageIndexToolkit(AbstractToolkit)`** — Toolkit exposing search / retrieve / insert tools over PageIndex trees.
