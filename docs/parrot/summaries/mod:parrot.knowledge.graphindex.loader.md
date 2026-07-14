---
type: Wiki Summary
title: parrot.knowledge.graphindex.loader
id: mod:parrot.knowledge.graphindex.loader
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: GraphIndexLoader — :class:`AbstractLoader` wrapper around GraphIndex.
relates_to:
- concept: class:parrot.knowledge.graphindex.loader.GraphIndexLoader
  rel: defines
- concept: mod:parrot.knowledge.graphindex
  rel: references
- concept: mod:parrot.knowledge.graphindex.embed
  rel: references
- concept: mod:parrot.knowledge.graphindex.meta_ontology
  rel: references
- concept: mod:parrot.knowledge.graphindex.persist
  rel: references
- concept: mod:parrot.knowledge.graphindex.persist_sqlite
  rel: references
- concept: mod:parrot.knowledge.graphindex.schema
  rel: references
- concept: mod:parrot.knowledge.ontology.graph_store
  rel: references
- concept: mod:parrot.knowledge.ontology.schema
  rel: references
- concept: mod:parrot.knowledge.pageindex.llm_adapter
  rel: references
- concept: mod:parrot.knowledge.pageindex.toolkit
  rel: references
- concept: mod:parrot.loaders.abstract
  rel: references
- concept: mod:parrot.stores.models
  rel: references
---

# `parrot.knowledge.graphindex.loader`

GraphIndexLoader — :class:`AbstractLoader` wrapper around GraphIndex.

This loader accepts a list of files and runs the **full**
:class:`~parrot.knowledge.graphindex.builder.GraphIndexBuilder` pipeline
(extract → embed → assemble → cross-domain resolve → analytics) over them,
emitting ``UniversalNode`` / ``UniversalEdge`` that are compatible with the rest
of the GraphIndex subsystem.

ArangoDB persistence is **optional**:

* When ArangoDB credentials are supplied (explicit kwargs or an ``arango``
  dict; missing fields are filled from ``ARANGODB_*`` env vars via
  ``navconfig``), the graph is persisted through
  :class:`~parrot.knowledge.graphindex.persist.GraphIndexPersistence` backed by
  an :class:`~parrot.knowledge.ontology.graph_store.OntologyGraphStore`.
* When no credentials are given, an in-process no-op persistence is used: the
  full pipeline still runs and the assembled graph is exposed in memory, but
  nothing is written to a database.

As with :class:`PageIndexLoader`, two views are offered: ``load()`` returns one
:class:`~parrot.stores.models.Document` per graph node, while
:meth:`build_graph` / the :pyattr:`nodes`, :pyattr:`edges`, :pyattr:`build_result`
attributes expose the native artifacts.

## Classes

- **`GraphIndexLoader(AbstractLoader)`** — Build a GraphIndex graph from a list of files.
