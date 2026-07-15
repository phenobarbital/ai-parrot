---
type: Wiki Summary
title: parrot.knowledge.pageindex.okf.concept_id
id: mod:parrot.knowledge.pageindex.okf.concept_id
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Deterministic slug generation for OKF concept identifiers.
relates_to:
- concept: func:parrot.knowledge.pageindex.okf.concept_id.assign_concept_ids
  rel: defines
- concept: func:parrot.knowledge.pageindex.okf.concept_id.dedup_concept_ids
  rel: defines
- concept: func:parrot.knowledge.pageindex.okf.concept_id.derive_concept_id
  rel: defines
---

# `parrot.knowledge.pageindex.okf.concept_id`

Deterministic slug generation for OKF concept identifiers.

Implements stable ``concept_id`` derivation from node titles and parent paths.
``concept_id`` is the stable identity anchor for the entire OKF layer — it
survives ``reindex_node_ids``, ``splice_subtree``, and ``delete_node`` operations.

Design notes (from spec §2, D3, D8):
- ``concept_id`` is a deterministic slug — same title + parent path → same slug.
- Collisions (duplicate titles at the same level) are resolved with numeric
  suffixes (``-2``, ``-3``, ...) that are stable across runs.
- The first occurrence in depth-first order keeps the bare slug.
- Slash-separated hierarchy levels encode parent/child relationships.
  The projection layer flattens slashes to ``--`` for filesystem storage.

## Functions

- `def derive_concept_id(title: str, parent_path: str='') -> str` — Derive a deterministic concept_id slug from a title.
- `def dedup_concept_ids(nodes: list[dict]) -> None` — Resolve slug collisions with stable numeric suffixes.
- `def assign_concept_ids(tree: dict[str, Any]) -> None` — Walk the tree depth-first and write deterministic ``concept_id`` values.
