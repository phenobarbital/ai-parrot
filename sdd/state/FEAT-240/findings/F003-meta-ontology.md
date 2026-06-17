---
id: F003
query_id: Q003
type: read
intent: Verify EDGE_KIND_TO_COLLECTION and RelationDef entries in meta_ontology.py
executed_at: 2026-06-16T00:00:00Z
duration_ms: 800
parent_id: null
depth: 0
---

# F003 — meta_ontology.py maps 5 edge kinds; no extends

## Summary

`meta_ontology.py` defines `EDGE_KIND_TO_COLLECTION` with 5 entries mapping to
`gi_contains`, `gi_references`, `gi_defines`, `gi_mentions`, `gi_explains`.
`_RELATION_DEFS` has corresponding `RelationDef` entries. Adding `"extends": "gi_extends"`
is mechanical. Only needed if ArangoDB backend must persist EXTENDS edges.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/meta_ontology.py`
  lines: 195-201
  symbol: `EDGE_KIND_TO_COLLECTION`
  excerpt: |
    EDGE_KIND_TO_COLLECTION: dict[str, str] = {
        "contains": "gi_contains",
        "references": "gi_references",
        "defines": "gi_defines",
        "mentions": "gi_mentions",
        "explains": "gi_explains",
    }

- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/meta_ontology.py`
  lines: 127-174
  symbol: `_RELATION_DEFS`
  excerpt: |
    # RelationDef entries for contains, references, defines, mentions, explains

## Notes

The brainstorm correctly notes the SQLite backend doesn't need this mapping
(edges are rows with a `kind` column). This change is only for ArangoDB parity.
