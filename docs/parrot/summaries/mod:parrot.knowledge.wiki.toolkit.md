---
type: Wiki Summary
title: parrot.knowledge.wiki.toolkit
id: mod:parrot.knowledge.wiki.toolkit
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: LLMWikiToolkit — agent-facing orchestrator for the LLM Wiki (FEAT-260).
relates_to:
- concept: class:parrot.knowledge.wiki.toolkit.LLMWikiToolkit
  rel: defines
- concept: mod:parrot.knowledge.wiki.bookkeeper
  rel: references
- concept: mod:parrot.knowledge.wiki.context
  rel: references
- concept: mod:parrot.knowledge.wiki.export
  rel: references
- concept: mod:parrot.knowledge.wiki.ingest
  rel: references
- concept: mod:parrot.knowledge.wiki.models
  rel: references
- concept: mod:parrot.knowledge.wiki.search
  rel: references
- concept: mod:parrot.knowledge.wiki.sources
  rel: references
- concept: mod:parrot.knowledge.wiki.store
  rel: references
- concept: mod:parrot.tools.toolkit
  rel: references
---

# `parrot.knowledge.wiki.toolkit`

LLMWikiToolkit — agent-facing orchestrator for the LLM Wiki (FEAT-260).

Composes :class:`PageIndexToolkit`, :class:`GraphIndexToolkit`, and
:class:`OKFToolkit` into Karpathy's 3-layer wiki architecture.  Every
public async method becomes an LLM-callable tool namespaced under the
``"wiki"`` prefix (e.g. ``wiki_ingest_source``, ``wiki_query``, etc.).

Layer mapping:
- **Raw Sources** — managed by :class:`SourceCollectionManager`
- **Wiki Pages** — stored in PageIndex trees; synced to GraphIndex nodes
- **Schema** — OKF ConceptType / RelationType extensions (FEAT-260)

All async methods accept JSON-serialisable arguments and return plain
dicts so that tool responses are directly usable as LLM context.

## Classes

- **`LLMWikiToolkit(AbstractToolkit)`** — Orchestrates PageIndex + GraphIndex + OKF into a persistent LLM wiki.
