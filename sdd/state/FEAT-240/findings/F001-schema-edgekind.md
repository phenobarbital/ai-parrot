---
id: F001
query_id: Q001
type: read
intent: Verify EdgeKind/NodeKind enums in schema.py — check if EXTENDS exists
executed_at: 2026-06-16T00:00:00Z
duration_ms: 1200
parent_id: null
depth: 0
---

# F001 — EdgeKind enum lacks EXTENDS; NodeKind has 6 members

## Summary

`schema.py` at `packages/ai-parrot/src/parrot/knowledge/graphindex/schema.py` defines
5 EdgeKind members: CONTAINS, REFERENCES, DEFINES, MENTIONS, EXPLAINS. **EXTENDS does
not exist.** NodeKind has 6 members: DOCUMENT, SECTION, SYMBOL, CONCEPT, RATIONALE, SKILL.
UniversalNode and UniversalEdge are Pydantic-style dataclasses with domain_tags as dict.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/schema.py`
  lines: 53-68
  symbol: `EdgeKind`
  excerpt: |
    class EdgeKind(str, Enum):
        CONTAINS = "contains"
        REFERENCES = "references"
        DEFINES = "defines"
        MENTIONS = "mentions"
        EXPLAINS = "explains"

- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/schema.py`
  lines: 33-50
  symbol: `NodeKind`
  excerpt: |
    class NodeKind(str, Enum):
        DOCUMENT = "document"
        SECTION = "section"
        SYMBOL = "symbol"
        CONCEPT = "concept"
        RATIONALE = "rationale"
        SKILL = "skill"

## Notes

Adding `EXTENDS = "extends"` is a one-line addition. No downstream code iterates
EdgeKind exhaustively, so this is backward-compatible.
