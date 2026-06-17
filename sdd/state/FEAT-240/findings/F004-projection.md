---
id: F004
query_id: Q004
type: read
intent: Verify EDGE_KIND_TO_RELATION_TYPE and RelationType extensibility
executed_at: 2026-06-16T00:00:00Z
duration_ms: 800
parent_id: null
depth: 0
---

# F004 — projection.py maps 5 edge kinds; RelationType trivially extensible

## Summary

`projection.py` (FEAT-239) maps EdgeKind→RelationType for OKF sidecar generation.
5 current mappings. `RelationType` lives at `parrot.knowledge.okf.ontology` and has
12 members (8 original + 4 from FEAT-239). Adding `EXTENDS = "extends"` is trivial —
FEAT-239 just added 4 new members in the same pattern.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/projection.py`
  lines: 65-71
  symbol: `EDGE_KIND_TO_RELATION_TYPE`
  excerpt: |
    EDGE_KIND_TO_RELATION_TYPE: dict[EdgeKind, RelationType] = {
        EdgeKind.CONTAINS: RelationType.CONTAINS,
        EdgeKind.REFERENCES: RelationType.REFERENCES,
        EdgeKind.DEFINES: RelationType.DEFINES,
        EdgeKind.MENTIONS: RelationType.MENTIONS,
        EdgeKind.EXPLAINS: RelationType.EXPLAINS,
    }

- path: `packages/ai-parrot/src/parrot/knowledge/okf/ontology.py`
  lines: 58-82
  symbol: `RelationType`
  excerpt: |
    class RelationType(str, Enum):
        REFERENCES = "references"
        MAPS_TO = "maps_to"
        SATISFIES = "satisfies"
        SATISFIED_BY = "satisfied_by"
        SUPERSEDES = "supersedes"
        SUPERSEDED_BY = "superseded_by"
        IMPLEMENTS = "implements"
        PART_OF = "part_of"
        DEFINES = "defines"
        MENTIONS = "mentions"
        EXPLAINS = "explains"
        CONTAINS = "contains"

## Notes

Brainstorm's decision (a) — add `RelationType.EXTENDS` — is clearly preferable.
The enum was just extended for FEAT-239 with zero friction. Option (b) (map to
REFERENCES) would lose semantic fidelity. Recommend (a).
