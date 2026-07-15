---
type: Wiki Summary
title: parrot.knowledge.pageindex.loader
id: mod:parrot.knowledge.pageindex.loader
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: PageIndexLoader — :class:`AbstractLoader` wrapper around PageIndex.
relates_to:
- concept: class:parrot.knowledge.pageindex.loader.PageIndexLoader
  rel: defines
- concept: mod:parrot.knowledge.pageindex.content_store
  rel: references
- concept: mod:parrot.knowledge.pageindex.llm_adapter
  rel: references
- concept: mod:parrot.knowledge.pageindex.schemas
  rel: references
- concept: mod:parrot.knowledge.pageindex.toolkit
  rel: references
- concept: mod:parrot.knowledge.pageindex.utils
  rel: references
- concept: mod:parrot.loaders.abstract
  rel: references
- concept: mod:parrot.stores.models
  rel: references
---

# `parrot.knowledge.pageindex.loader`

PageIndexLoader — :class:`AbstractLoader` wrapper around PageIndex.

This loader accepts a list of files (PDF / Markdown / plain text), drives the
existing :class:`~parrot.knowledge.pageindex.toolkit.PageIndexToolkit` to build a
single hierarchical **PageIndex tree** (a lean ToC tree plus per-node markdown
sidecars persisted under ``storage_dir``), and exposes the result through the
familiar loader contract.

Two complementary views of the same build are offered:

* ``load()`` returns **one** :class:`~parrot.stores.models.Document` **per tree
  node** so the output flows straight into the existing RAG / vector-store
  pipeline. Re-chunking is disabled by default because tree nodes are already
  bounded retrieval units.
* :meth:`build_tree` / the :pyattr:`tree` property return the **native** tree
  dict (validated against :class:`PageIndexTree`), and :pyattr:`toolkit`
  exposes the underlying toolkit for downstream hybrid search / retrieval.

Persistence is mandatory (decision recorded in the feature plan): a
``storage_dir`` must be supplied and every tree is written to disk via the
toolkit so it is immediately searchable afterwards.

## Classes

- **`PageIndexLoader(AbstractLoader)`** — Build a PageIndex tree from a list of files.
