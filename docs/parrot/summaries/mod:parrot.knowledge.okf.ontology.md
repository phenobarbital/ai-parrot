---
type: Wiki Summary
title: parrot.knowledge.okf.ontology
id: mod:parrot.knowledge.okf.ontology
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Shared OKF type vocabulary — single source of truth for all indexes.
relates_to:
- concept: class:parrot.knowledge.okf.ontology.ConceptType
  rel: defines
- concept: class:parrot.knowledge.okf.ontology.RelatesTo
  rel: defines
- concept: class:parrot.knowledge.okf.ontology.RelationType
  rel: defines
- concept: class:parrot.knowledge.okf.ontology.SourceProvenance
  rel: defines
---

# `parrot.knowledge.okf.ontology`

Shared OKF type vocabulary — single source of truth for all indexes.

This module is the canonical home for the OKF controlled type vocabulary,
previously resident in ``pageindex/okf/ontology.py``.  Both PageIndex and
GraphIndex import from here, avoiding an inverted dependency between sibling
packages.

FEAT-239: Extended with 5 graph-native ``ConceptType`` values and 4 graph
edge kinds for ``RelationType``.

FEAT-240: Added ``RelationType.EXTENDS`` for Odoo model inheritance edges.

Design notes:
- ``ConceptType`` values for existing members MUST remain identical strings
  (e.g. ``"Section"``, ``"Policy"``) to avoid breaking YAML frontmatter parsing.
- New graph-native type values use title-case: ``"Symbol"``, ``"Rationale"``, etc.
- ``RelationType.REFERENCES`` is the default for untyped prose link fallback.
- ``ConceptType.SECTION`` is the structural fallback when LLM classification is
  unavailable — and is directly reusable for both PageIndex sections and GraphIndex
  SECTION nodes because both use the same string value ``"Section"``.

## Classes

- **`ConceptType(str, Enum)`** — Controlled ontological vocabulary for OKF node types.
- **`RelationType(str, Enum)`** — Typed edge vocabulary (OKF-superset).
- **`RelatesTo(BaseModel)`** — A typed edge in the knowledge graph.
- **`SourceProvenance(BaseModel)`** — Per-node provenance, citable.
