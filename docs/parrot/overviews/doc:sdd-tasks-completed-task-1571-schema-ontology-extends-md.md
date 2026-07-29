---
type: Wiki Overview
title: 'TASK-1571: Schema & Ontology Prerequisites — Add EdgeKind.EXTENDS'
id: doc:sdd-tasks-completed-task-1571-schema-ontology-extends-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This is the prerequisite task for FEAT-240. All other tasks depend on the
relates_to:
- concept: mod:parrot.knowledge.graphindex.schema
  rel: mentions
- concept: mod:parrot.knowledge.okf.ontology
  rel: mentions
---

# TASK-1571: Schema & Ontology Prerequisites — Add EdgeKind.EXTENDS

**Feature**: FEAT-240 — GraphIndex Odoo-aware Extractor + SQLite Persistence + Graph Reader
**Spec**: `sdd/specs/odoo-graphindex-code.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the prerequisite task for FEAT-240. All other tasks depend on the
`EdgeKind.EXTENDS` enum member and its mappings across the schema, ontology,
meta-ontology, and projection layers.

Implements Spec §3 Module 1.

---

## Scope

- Add `EXTENDS = "extends"` to `EdgeKind` enum in `schema.py`
- Add `EXTENDS = "extends"` to `RelationType` enum in `okf/ontology.py`
- Add `"extends": "gi_extends"` to `EDGE_KIND_TO_COLLECTION` in `meta_ontology.py`
- Add a `RelationDef("extends", ...)` entry to `_RELATION_DEFS` in `meta_ontology.py`
- Add `EdgeKind.EXTENDS: RelationType.EXTENDS` to `EDGE_KIND_TO_RELATION_TYPE` in `projection.py`
- Update existing tests if they assert on enum member counts or dict contents

**NOT in scope**: SQLitePersistence, OdooCodeExtractor, SQLiteGraphReader, builder changes

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/schema.py` | MODIFY | Add `EXTENDS` to `EdgeKind` |
| `packages/ai-parrot/src/parrot/knowledge/okf/ontology.py` | MODIFY | Add `EXTENDS` to `RelationType` |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/meta_ontology.py` | MODIFY | Add `gi_extends` mapping + `RelationDef` |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/projection.py` | MODIFY | Add EXTENDS to mapping dict |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.graphindex.schema import EdgeKind  # verified: schema.py:53
from parrot.knowledge.okf.ontology import RelationType    # verified: ontology.py:58
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/graphindex/schema.py
class EdgeKind(str, Enum):       # line 53
    CONTAINS = "contains"         # line 64
    REFERENCES = "references"     # line 65
    DEFINES = "defines"           # line 66
    MENTIONS = "mentions"         # line 67
    EXPLAINS = "explains"         # line 68
    # ADD: EXTENDS = "extends"

# packages/ai-parrot/src/parrot/knowledge/okf/ontology.py
class RelationType(str, Enum):   # line 58
    # ... existing members through line 81
    CONTAINS = "contains"         # line 81
    # ADD: EXTENDS = "extends"

# packages/ai-parrot/src/parrot/knowledge/graphindex/meta_ontology.py
EDGE_KIND_TO_COLLECTION: dict[str, str] = {  # line 195
    "contains": "gi_contains",     # line 196
    "references": "gi_references", # line 197
    "defines": "gi_defines",       # line 198
    "mentions": "gi_mentions",     # line 199
    "explains": "gi_explains",     # line 200
}                                  # line 201
# ADD: "extends": "gi_extends"

# packages/ai-parrot/src/parrot/knowledge/graphindex/projection.py
EDGE_KIND_TO_RELATION_TYPE: dict[EdgeKind, RelationType] = {  # line 65
    EdgeKind.CONTAINS: RelationType.CONTAINS,    # line 66
    EdgeKind.REFERENCES: RelationType.REFERENCES,# line 67
    EdgeKind.DEFINES: RelationType.DEFINES,      # line 68
    EdgeKind.MENTIONS: RelationType.MENTIONS,    # line 69
    EdgeKind.EXPLAINS: RelationType.EXPLAINS,    # line 70
}                                                 # line 71
# ADD: EdgeKind.EXTENDS: RelationType.EXTENDS
```

### Does NOT Exist
- ~~`EdgeKind.EXTENDS`~~ — does not exist yet; this task creates it
- ~~`RelationType.EXTENDS`~~ — does not exist yet; this task creates it
- ~~`gi_extends` collection~~ — not in EDGE_KIND_TO_COLLECTION yet

---

## Implementation Notes

### Pattern to Follow

Follow the exact pattern of the existing enum members. For `_RELATION_DEFS`,
copy the structure of the `"defines"` entry and adapt for `"extends"`:

```python
"extends": RelationDef(
    name="extends",
    edge_collection="gi_extends",
    from_collections=[...],  # same as defines
    to_collections=[...],
)
```

### Key Constraints
- Do NOT change the order of existing enum members
- Do NOT rename existing members
- Maintain alphabetical comment grouping where present

---

## Acceptance Criteria

- [ ] `EdgeKind.EXTENDS` exists and `EdgeKind("extends")` resolves
- [ ] `RelationType.EXTENDS` exists and `RelationType("extends")` resolves
- [ ] `EDGE_KIND_TO_COLLECTION["extends"] == "gi_extends"`
- [ ] `EDGE_KIND_TO_RELATION_TYPE[EdgeKind.EXTENDS] == RelationType.EXTENDS`
- [ ] All existing graphindex tests pass: `pytest packages/ai-parrot/tests/knowledge/graphindex/ -v`
- [ ] All existing OKF tests pass: `pytest packages/ai-parrot/tests/knowledge/okf/ -v`

---

## Test Specification

No new test file needed — existing tests cover enum completeness. Verify
with the existing test suite. If any test asserts exact enum member counts,
update the expected count.

---

## Completion Note

Added `EdgeKind.EXTENDS = "extends"` to `schema.py`, `RelationType.EXTENDS = "extends"` to
`okf/ontology.py`, `"extends": "gi_extends"` to `EDGE_KIND_TO_COLLECTION` in
`meta_ontology.py`, a `RelationDef("extends", ...)` entry in `_RELATION_DEFS`, and
`EdgeKind.EXTENDS: RelationType.EXTENDS` to `EDGE_KIND_TO_RELATION_TYPE` in `projection.py`.
Updated the OKF test that asserts exact enum member count from 12 to 13 (adding new test for
EXTENDS value). All 72 graphindex + OKF tests pass.
