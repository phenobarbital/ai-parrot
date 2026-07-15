---
type: Wiki Summary
title: parrot.knowledge.pageindex.okf.migrate
id: mod:parrot.knowledge.pageindex.okf.migrate
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: 'okf-migrate: Retrofit existing PageIndex trees with OKF fields.'
relates_to:
- concept: class:parrot.knowledge.pageindex.okf.migrate.MigrationReport
  rel: defines
- concept: func:parrot.knowledge.pageindex.okf.migrate.okf_migrate
  rel: defines
- concept: mod:parrot.knowledge.pageindex.content_store
  rel: references
- concept: mod:parrot.knowledge.pageindex.okf.concept_id
  rel: references
- concept: mod:parrot.knowledge.pageindex.okf.graph
  rel: references
- concept: mod:parrot.knowledge.pageindex.okf.ontology
  rel: references
- concept: mod:parrot.knowledge.pageindex.okf.projection
  rel: references
- concept: mod:parrot.knowledge.pageindex.store
  rel: references
- concept: mod:parrot.knowledge.pageindex.utils
  rel: references
---

# `parrot.knowledge.pageindex.okf.migrate`

okf-migrate: Retrofit existing PageIndex trees with OKF fields.

This module provides ``okf_migrate()`` — the main migration command that
enriches a bare PageIndex tree with OKF fields:

1. Derives ``concept_id`` for every node via ``assign_concept_ids()``.
2. Classifies ``type`` via LLM with content-addressed caching; falls back
   to ``ConceptType.SECTION`` when LLM is unavailable or the adapter is
   ``None``.
3. Builds ``source`` provenance from ``doc_name`` + ``start_index``/``end_index``.
4. Parses sidecar body markdown links → ``relates_to`` candidates
   (``rel: references``).
5. Renames sidecars ``<node_id>.md`` → ``<flattened_concept_id>.md`` with
   projected frontmatter.
6. Generates root ``index.md``.
7. Saves the enriched tree JSON.
8. Emits a ``MigrationReport``.

The command is **idempotent**: re-running on an already-migrated tree
produces identical output.  Content-addressed type cache ensures LLM is
called at most once per (model_id, title, summary) tuple.

Design notes (spec §3 Module 6, D3, D8, D10):
- Only explicit markdown links become ``relates_to``; LLM-inferred edges
  are deferred to the HITL-gated pass.
- ``force_reclassify=True`` bypasses the content-addressed cache.
- Cache is persisted as a JSON sidecar alongside the tree.

## Classes

- **`MigrationReport(BaseModel)`** — Report produced by ``okf_migrate()``.

## Functions

- `async def okf_migrate(tree_name: str, tree_store: JSONTreeStore, content_store: NodeContentStore, adapter: Any, *, force_reclassify: bool=False) -> MigrationReport` — Retrofit an existing PageIndex tree with OKF fields.
