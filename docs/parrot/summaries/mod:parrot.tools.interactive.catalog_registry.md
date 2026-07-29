---
type: Wiki Summary
title: parrot.tools.interactive.catalog_registry
id: mod:parrot.tools.interactive.catalog_registry
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: On-disk loader for the interactive HTML artifact catalog.
relates_to:
- concept: class:parrot.tools.interactive.catalog_registry.InteractiveCatalogRegistry
  rel: defines
- concept: func:parrot.tools.interactive.catalog_registry.build_head
  rel: defines
- concept: func:parrot.tools.interactive.catalog_registry.get_interactive_catalog
  rel: defines
- concept: mod:parrot.models.infographic
  rel: references
- concept: mod:parrot.models.interactive
  rel: references
---

# `parrot.tools.interactive.catalog_registry`

On-disk loader for the interactive HTML artifact catalog.

The catalog ships two kinds of entries under
``parrot/tools/interactive/catalog/``:

- ``libraries/*.md`` — YAML frontmatter describing a vetted JS library plus
  fenced ``## Usage`` / ``## Types`` / ``## Inline`` code blocks. Parsed into
  :class:`~parrot.models.interactive.LibraryEntry`.
- ``templates/<name>.html`` + ``templates/<name>.meta.yaml`` — a self-contained
  HTML skeleton with ``<!-- SLOT:name -->`` markers and a ``<!--HEAD-->`` marker,
  plus metadata (description, default theme, allowed libraries). Parsed into
  :class:`~parrot.models.interactive.ScaffoldTemplate` (slots auto-derived from
  the skeleton).

The registry follows the eager-load + index pattern of
:class:`~parrot.skills.file_registry.SkillFileRegistry`. A module-level singleton
is exposed via :func:`get_interactive_catalog`.

This module also owns the deterministic presentation layer reused by the
toolkit: :data:`BASE_CSS`, the theme variable map, and :func:`build_head`, which
assembles the ``<head>`` injection (base CSS + theme variables + allow-listed
bundle ``<script>``/``<link>`` tags) that replaces a skeleton's ``<!--HEAD-->``
marker.

## Classes

- **`InteractiveCatalogRegistry`** — Eager-loading registry of catalog libraries and scaffold templates.

## Functions

- `def build_head(bundles: Iterable[JSBundle], theme: Optional[str]=None) -> str` — Assemble the ``<head>`` injection for a skeleton's ``<!--HEAD-->`` marker.
- `def get_interactive_catalog() -> InteractiveCatalogRegistry` — Return the process-wide catalog singleton (not yet loaded).
