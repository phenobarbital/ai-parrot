---
type: Wiki Summary
title: parrot.knowledge.wiki.search
id: mod:parrot.knowledge.wiki.search
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Combined search for the LLM Wiki (FEAT-260 + WikiStore plane).
relates_to:
- concept: class:parrot.knowledge.wiki.search.WikiCombinedSearch
  rel: defines
- concept: mod:parrot.knowledge.wiki.models
  rel: references
- concept: mod:parrot.knowledge.wiki.store
  rel: references
---

# `parrot.knowledge.wiki.search`

Combined search for the LLM Wiki (FEAT-260 + WikiStore plane).

Preferred path — when a :class:`WikiStore` is provided, every query is
answered directly from the single-file SQLite plane (no toolkit
fan-out, no markdown parsing at query time):

- **lexical** — FTS5/BM25 over title/summary/body.
- **vector** — cosine over stored page embeddings (requires an
  ``embedder`` callable).
- ``"combined"`` (default) merges both with configurable weights.
  Legacy mode names map onto the plane: ``"pageindex"`` → lexical,
  ``"graphindex"`` → vector.

Legacy path — without a store, results are merged from
``PageIndexToolkit.search()`` and ``GraphIndexToolkit.search_hybrid()``
exactly as before (kept for one release).

Results from each group are min-max normalised to [0, 1], weighted by
the configurable ``search_weights`` dictionary, deduplicated by
``node_id``, and returned as a sorted :class:`WikiSearchResult` list.

## Classes

- **`WikiCombinedSearch`** — Unified search across PageIndex and GraphIndex.
