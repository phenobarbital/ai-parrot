---
type: Wiki Summary
title: parrot.knowledge.okf.frontmatter
id: mod:parrot.knowledge.okf.frontmatter
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Frontmatter model and deterministic YAML projection for OKF sidecars.
relates_to:
- concept: class:parrot.knowledge.okf.frontmatter.ConceptFrontmatter
  rel: defines
- concept: func:parrot.knowledge.okf.frontmatter.parse_frontmatter
  rel: defines
- concept: func:parrot.knowledge.okf.frontmatter.project_frontmatter
  rel: defines
- concept: mod:parrot.knowledge.okf.ontology
  rel: references
---

# `parrot.knowledge.okf.frontmatter`

Frontmatter model and deterministic YAML projection for OKF sidecars.

The frontmatter is the deterministic mirror of the authoritative JSON node
onto each sidecar ``.md`` file.  The projection is:

- **Pure function**: same JSON node → same YAML bytes every time.
- **Single-writer**: only ``project_frontmatter`` writes frontmatter; no
  hand-edits to sidecar frontmatter are valid (they will be overwritten).
- **Byte-deterministic**: field order is fixed, values are verbatim from JSON.

Moved from ``parrot.knowledge.pageindex.okf.frontmatter`` to the shared
``parrot.knowledge.okf`` package (FEAT-239) to allow GraphIndex to reuse
the engine without an inverted dependency.  The original module is now a
thin re-export shim for backwards compatibility.

Design notes (from spec §2.2, D1, D11):
- ``summary`` reuses the FEAT-199 embedding target text — one source, zero divergence.
- ``tags`` are sorted alphabetically for determinism.
- Optional fields (``source``, ``url``) are omitted when ``None``.
- Frontmatter delimiters are ``---\n`` (start) and ``---\n`` (end).

## Classes

- **`ConceptFrontmatter(BaseModel)`** — Pydantic v2 model for the deterministic frontmatter projection.

## Functions

- `def project_frontmatter(node: dict, tree_name: str) -> str` — Produce a byte-deterministic YAML frontmatter string from a node dict.
- `def parse_frontmatter(text: str) -> ConceptFrontmatter` — Parse YAML frontmatter from a sidecar string back into a model.
