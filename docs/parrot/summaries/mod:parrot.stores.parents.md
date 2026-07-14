---
type: Wiki Summary
title: parrot.stores.parents
id: mod:parrot.stores.parents
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Parent document searcher package for FEAT-128 — Parent-Child Retrieval.
relates_to:
- concept: mod:parrot.stores.parents.abstract
  rel: references
- concept: mod:parrot.stores.parents.in_table
  rel: references
---

# `parrot.stores.parents`

Parent document searcher package for FEAT-128 — Parent-Child Retrieval.

This package provides the composable :class:`AbstractParentSearcher` interface
and the default :class:`InTableParentSearcher` implementation that fetches
parent documents from the same vector table as child chunks.

Usage::

    from parrot.stores.parents import AbstractParentSearcher, InTableParentSearcher

    # Default in-table searcher (postgres / pgvector)
    searcher = InTableParentSearcher(store=pg_store)
    parents = await searcher.fetch(['parent-id-1', 'parent-id-2'])
