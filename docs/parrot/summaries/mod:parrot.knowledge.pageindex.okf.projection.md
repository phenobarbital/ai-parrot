---
type: Wiki Summary
title: parrot.knowledge.pageindex.okf.projection
id: mod:parrot.knowledge.pageindex.okf.projection
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Deterministic sidecar and index.md generation for OKF.
relates_to:
- concept: class:parrot.knowledge.pageindex.okf.projection.ProjectionReport
  rel: defines
- concept: func:parrot.knowledge.pageindex.okf.projection.generate_index_md
  rel: defines
- concept: func:parrot.knowledge.pageindex.okf.projection.project_sidecar
  rel: defines
- concept: func:parrot.knowledge.pageindex.okf.projection.project_sidecars
  rel: defines
- concept: mod:parrot.knowledge.okf.frontmatter
  rel: references
- concept: mod:parrot.knowledge.okf.utils
  rel: references
- concept: mod:parrot.knowledge.pageindex.content_store
  rel: references
- concept: mod:parrot.knowledge.pageindex.utils
  rel: references
---

# `parrot.knowledge.pageindex.okf.projection`

Deterministic sidecar and index.md generation for OKF.

This module is the "single writer" that projects the authoritative JSON tree
onto disk.  It:

- Generates frontmatter-enriched sidecars (``<flattened_concept_id>.md``) for
  every node in the tree.
- Writes a root-level ``index.md`` listing of the JSON ToC.

Both outputs are **pure functions of the JSON** — regenerating from the same
tree MUST produce byte-identical files.  Single-writer; no hand-edits survive.

Design notes (from spec §2.2, D1, D8):
- Sidecar filenames are ``<flattened_concept_id>.md``.
  Slashes in concept_id are encoded as ``--`` (double-dash) for filesystem
  compatibility, because ``_NODE_ID_RE`` only allows ``[A-Za-z0-9_-]{1,64}``.
- Body content is preserved verbatim; only the frontmatter header is
  prepended/replaced.
- Old ``<node_id>.md`` sidecars are cleaned up when a concept_id sidecar is
  written.

## Classes

- **`ProjectionReport(BaseModel)`** — Report returned by project_sidecars().

## Functions

- `def project_sidecar(node: dict, tree_name: str, body: str) -> str` — Combine projected frontmatter and existing body into a sidecar string.
- `def project_sidecars(tree: dict, tree_name: str, content_store: NodeContentStore) -> ProjectionReport` — Regenerate all sidecars from the authoritative JSON tree.
- `def generate_index_md(tree: dict, tree_name: str) -> str` — Generate a deterministic root-level index.md view of the JSON ToC.
