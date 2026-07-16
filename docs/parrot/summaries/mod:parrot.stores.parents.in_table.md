---
type: Wiki Summary
title: parrot.stores.parents.in_table
id: mod:parrot.stores.parents.in_table
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: In-table parent searcher for pgvector stores.
relates_to:
- concept: class:parrot.stores.parents.in_table.InTableParentSearcher
  rel: defines
- concept: mod:parrot.stores.abstract
  rel: references
- concept: mod:parrot.stores.models
  rel: references
- concept: mod:parrot.stores.parents.abstract
  rel: references
---

# `parrot.stores.parents.in_table`

In-table parent searcher for pgvector stores.

This module implements :class:`InTableParentSearcher`, the default
``AbstractParentSearcher`` for deployments that store both chunks and their
parent documents in the same vector table (postgres / pgvector).

**Implementation approach (Approach A — direct connection access)**:

The searcher uses the store's ``session()`` async context manager and issues
a single parameterised SQL query per ``fetch()`` call.  This avoids the N+1
pattern that would arise from fetching each parent individually.

The SQL semantics are:

.. code-block:: sql

    SELECT <id_col>, <doc_col>, <meta_col>
    FROM <schema>.<table>
    WHERE <id_col> = ANY(:ids)
      AND (
        (<meta_col>->>'is_full_document')::boolean = true
        OR <meta_col>->>'document_type' = 'parent_chunk'
      )

This single round trip covers both 2-level parents (``is_full_document=True``)
and 3-level intermediate parent chunks (``document_type='parent_chunk'``).

## Classes

- **`InTableParentSearcher(AbstractParentSearcher)`** — Fetch parents from the same vector table by metadata filter.
