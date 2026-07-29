---
type: Wiki Summary
title: parrot.knowledge.pageindex.okf.bundle
id: mod:parrot.knowledge.pageindex.okf.bundle
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: OKF v0.1 bundle import/export for PageIndex.
relates_to:
- concept: class:parrot.knowledge.pageindex.okf.bundle.ExportReport
  rel: defines
- concept: class:parrot.knowledge.pageindex.okf.bundle.ImportReport
  rel: defines
- concept: func:parrot.knowledge.pageindex.okf.bundle.export_okf_bundle
  rel: defines
- concept: func:parrot.knowledge.pageindex.okf.bundle.import_okf_bundle
  rel: defines
- concept: mod:parrot.knowledge.pageindex.content_store
  rel: references
- concept: mod:parrot.knowledge.pageindex.okf.concept_id
  rel: references
- concept: mod:parrot.knowledge.pageindex.okf.graph
  rel: references
- concept: mod:parrot.knowledge.pageindex.okf.ontology
  rel: references
- concept: mod:parrot.knowledge.pageindex.okf.projection
  rel: references
- concept: mod:parrot.knowledge.pageindex.store
  rel: references
- concept: mod:parrot.knowledge.pageindex.utils
  rel: references
---

# `parrot.knowledge.pageindex.okf.bundle`

OKF v0.1 bundle import/export for PageIndex.

Provides two public functions:

- :func:`export_okf_bundle` — Writes a PageIndex tree as an OKF v0.1 compliant
  directory bundle.  Files are grouped by concept type (``policies/``,
  ``controls/``, etc.), ``pageindex://`` URIs are rewritten to relative
  markdown paths, and AI-Parrot-specific fields (``node_id``, ``resource``)
  are stripped from frontmatter.

- :func:`import_okf_bundle` — Reads an OKF bundle directory into a new
  PageIndex tree.  YAML frontmatter is parsed from each ``.md`` file; unknown
  ``type`` values are mapped to :data:`ConceptType.OTHER`.  Markdown
  hyperlinks in bodies are resolved to ``relates_to`` edges.

Round-trip guarantee: export → import preserves ``concept_id``, ``type``,
``relates_to``, and body content.

Design notes (spec §2, §3 Modules 3 & 4):
- Export follows the ``project_sidecars()`` iteration pattern.
- Import uses two passes: first to collect concept_ids, second to resolve links.
- ``index.md`` files are generated on export and skipped on import.
- URI rewriting handles only ``pageindex://`` scheme URIs; absolute URLs and
  anchor-only links are left unchanged.

## Classes

- **`ExportReport(BaseModel)`** — Result of an OKF bundle export operation.
- **`ImportReport(BaseModel)`** — Result of an OKF bundle import operation.

## Functions

- `def export_okf_bundle(tree: dict, tree_name: str, content_store: NodeContentStore, output_dir: Path) -> ExportReport` — Export a PageIndex tree as an OKF v0.1 compliant directory bundle.
- `def import_okf_bundle(input_dir: Path, tree_name: str, store: JSONTreeStore, content_store: NodeContentStore) -> ImportReport` — Import an OKF bundle directory into a new PageIndex tree.
