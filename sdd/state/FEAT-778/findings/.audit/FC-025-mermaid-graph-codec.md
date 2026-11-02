---
id: FC-025
query_id: Q044
type: grep
intent: "Structured-output precedent for catalogue-as-source-of-truth + derived view (ComponentCatalogue / Mermaid)."
executed_at: 2026-10-30T16:46:28Z
duration_ms: 300
parent_id: null
depth: 0
---

# FC-025 — `parrot/outputs/a2ui/graph/` already has a `Graph` vocabulary with a deterministic Mermaid import/export codec (FEAT-529 Module 3) and a `mermaiddiagram` A2UI component; no `ComponentCatalogue`

## Summary

Matches cluster in `outputs/a2ui/graph/mermaid.py` (50), `mermaid_source.py` (45), `mermaid_c4.py` (34), `catalog/parrot/mermaiddiagram.py` (27), `graph/__init__.py`, `graph/models.py`. The docstring states Mermaid is "a deterministic IMPORT/EXPORT codec only" over the `Graph` models — i.e. structured model as source of truth, Mermaid as derived view, exactly the pattern the source wants for Domain Design. No `Catalogue`/`catalog_yaml` identifiers.

## Citations

- path: `packages/ai-parrot/src/parrot/outputs/a2ui/graph/mermaid.py`
  lines: 1-10
  symbol: `mermaid codec docstring`
  excerpt: |
    """Pure-Python Mermaid codec for the ``Graph`` vocabulary (FEAT-529 Module 3).
    Mermaid is a deterministic IMPORT/EXPORT codec only — ...
    Supported subset (spec §3 Module 3):

- path: `packages/ai-parrot/src/parrot/outputs/a2ui/graph/models.py`
  lines: 1
  symbol: `Graph models`
  excerpt: |
    (Graph vocabulary models)

- path: `packages/ai-parrot/src/parrot/outputs/a2ui/graph/mermaid_c4.py`
  lines: 1
  symbol: `C4 mermaid`
  excerpt: |
    (34 mermaid mentions — C4 diagram flavour)

- path: `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/mermaiddiagram.py`
  lines: 1
  symbol: `mermaiddiagram component`
  excerpt: |
    (A2UI catalog component rendering a Mermaid diagram)

## Notes

A `ComponentCatalogue` could serialize to this `Graph` vocabulary instead of defining a second diagram path.
