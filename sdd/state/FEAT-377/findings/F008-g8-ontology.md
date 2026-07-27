---
id: F008
query: "G8 — GraphIndex ontology gaps"
type: code_review
verdict: CONFIRMED
---

## G8: Arango meta-ontology covers 6 of 9 NodeKinds

**Verdict: CONFIRMED**

### Evidence

1. **`schema.py:36-61`** — `NodeKind` enum has 9 values:
   DOCUMENT, SECTION, SYMBOL, CONCEPT, RATIONALE, SKILL, WIKI_PAGE, RUN, CLAIM

2. **`meta_ontology.py:30-120`** — `_ENTITY_DEFS` defines only 6:
   document, section, symbol, concept, rationale, skill.
   Docstring confirms: "6 entity types."

3. **`meta_ontology.py:201`** — `KIND_TO_COLLECTION` maps only 6 kinds.
   `wiki_page`, `run`, `claim` have no collection mapping.

4. **`persist.py:240`** — `_upsert_nodes`: nodes with unmapped kinds hit
   `logger.warning("Unknown kind '%s'...")` and are silently skipped.

5. **Edge gap too**: `EDGE_KIND_TO_COLLECTION` maps 6 of 10 `EdgeKind` values.
   `PRODUCED`, `ABOUT`, `SUPPORTED_BY`, `CONTRADICTS` have no edge collection
   and are dropped by `_create_edges`.

### Impact

Before G2 seams 2-3 (run write-back, grounding) can land, the ontology
must be extended or SQLite must be documented as the sole plane for
memory kinds. This is a prerequisite for FEAT-B.
