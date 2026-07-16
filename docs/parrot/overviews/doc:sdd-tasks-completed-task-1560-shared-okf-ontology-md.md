---
type: Wiki Overview
title: 'TASK-1560: Create Shared OKF Ontology Package + PageIndex Re-exports'
id: doc:sdd-tasks-completed-task-1560-shared-okf-ontology-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This is the foundation task for FEAT-239. The OKF type vocabulary
relates_to:
- concept: mod:parrot.knowledge
  rel: mentions
- concept: mod:parrot.knowledge.okf
  rel: mentions
- concept: mod:parrot.knowledge.okf.ontology
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.okf
  rel: mentions
---

# TASK-1560: Create Shared OKF Ontology Package + PageIndex Re-exports

**Feature**: FEAT-239 — GraphIndex OKF Frontmatter Projection
**Spec**: `sdd/specs/graphindex-frontmatter.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the foundation task for FEAT-239. The OKF type vocabulary
(`ConceptType`, `RelationType`, `RelatesTo`, `SourceProvenance`) currently
lives in `pageindex/okf/ontology.py`. To allow GraphIndex to reuse these
types without an inverted dependency (graph → page), we extract them into a
shared `parrot/knowledge/okf/` package. The PageIndex module becomes a thin
re-export shim for backwards compatibility.

Implements spec §2 (Architectural Design) and §3 Module 1 + Module 4 (partial).

---

## Scope

- Create the `parrot/knowledge/okf/` package with `__init__.py` and `ontology.py`.
- Move `ConceptType`, `RelationType`, `RelatesTo`, `SourceProvenance` from
  `pageindex/okf/ontology.py` into `knowledge/okf/ontology.py`.
- Extend `ConceptType` with 5 graph-native values: `SYMBOL`, `RATIONALE`,
  `SKILL`, `CONCEPT_NODE`, `DOCUMENT_NODE`.
- Extend `RelationType` with 4 graph edge kinds: `DEFINES`, `MENTIONS`,
  `EXPLAINS`, `CONTAINS`.
- Replace `pageindex/okf/ontology.py` with a thin re-export shim that imports
  everything from `knowledge.okf.ontology` and re-exports via `__all__`.
- Update `pageindex/okf/__init__.py` to import ontology types from
  `knowledge.okf.ontology` (or keep importing from the shim — either works).
- Write unit tests for extended types in `tests/knowledge/okf/test_ontology.py`.
- Verify all 20 FEAT-238 tests still pass (backwards compatibility).

**NOT in scope**: Moving frontmatter engine (TASK-1561), URI scheme (TASK-1562),
GraphIndex projection code (TASK-1563).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/okf/__init__.py` | CREATE | Package init with exports |
| `packages/ai-parrot/src/parrot/knowledge/okf/ontology.py` | CREATE | Shared type vocabulary |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/ontology.py` | MODIFY | Thin re-export shim |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/__init__.py` | MODIFY | Update import source |
| `packages/ai-parrot/tests/knowledge/okf/__init__.py` | CREATE | Test package init |
| `packages/ai-parrot/tests/knowledge/okf/test_ontology.py` | CREATE | Unit tests for extended types |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Current imports that MUST continue to work after this task:
from parrot.knowledge.pageindex.okf import ConceptType       # pageindex/okf/__init__.py:16
from parrot.knowledge.pageindex.okf import RelationType       # pageindex/okf/__init__.py:17
from parrot.knowledge.pageindex.okf import RelatesTo          # pageindex/okf/__init__.py:18
from parrot.knowledge.pageindex.okf import SourceProvenance   # pageindex/okf/__init__.py:19

# NEW imports that must work after this task:
from parrot.knowledge.okf.ontology import ConceptType         # (new file)
from parrot.knowledge.okf.ontology import RelationType        # (new file)
from parrot.knowledge.okf.ontology import RelatesTo           # (new file)
from parrot.knowledge.okf.ontology import SourceProvenance    # (new file)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/okf/ontology.py
class ConceptType(str, Enum):          # line 21
    SECTION = "Section"                # line 22
    POLICY = "Policy"                  # line 23
    CONTROL = "Control"                # line 24
    SAFEGUARD = "Safeguard"            # line 25
    EVIDENCE = "Evidence"              # line 26
    PLAYBOOK = "Playbook"              # line 27
    PROCEDURE = "Procedure"            # line 28
    STANDARD = "Standard"              # line 29
    FRAMEWORK = "Framework"            # line 30
    REGULATION = "Regulation"          # line 31
    GUIDELINE = "Guideline"            # line 32

class RelationType(str, Enum):         # line 40
    REFERENCES = "references"          # line 41
    MAPS_TO = "maps_to"                # line 42
    SATISFIES = "satisfies"            # line 43
    SATISFIED_BY = "satisfied_by"      # line 44
    SUPERSEDES = "supersedes"          # line 45
    SUPERSEDED_BY = "superseded_by"    # line 46
    IMPLEMENTS = "implements"          # line 47
    PART_OF = "part_of"                # line 48

class RelatesTo(BaseModel):            # line 56
    concept: str                       # line 57
    rel: RelationType = RelationType.REFERENCES  # line 58

class SourceProvenance(BaseModel):     # line 71
    document: str                      # line 72
    pages: Optional[list[int]] = None  # line 73
    url: Optional[str] = None          # line 76

# pageindex/okf/__init__.py exports (20 items, lines 50-72)
# The __all__ list includes: ConceptType, RelationType, RelatesTo,
# SourceProvenance, derive_concept_id, dedup_concept_ids,
# assign_concept_ids, ConceptFrontmatter, project_frontmatter,
# parse_frontmatter, KnowledgeGraph, build_graph, parse_markdown_links,
# flatten_concept_id_for_filename, project_sidecar, project_sidecars,
# generate_index_md, ProjectionReport, okf_migrate, MigrationReport,
# OKFToolkit
```

### Does NOT Exist
- ~~`parrot.knowledge.okf`~~ — does not exist yet; this task creates it
- ~~`ConceptType.SYMBOL`~~ — not in current enum; this task adds it
- ~~`RelationType.DEFINES`~~ — not in current enum; this task adds it
- ~~`parrot.knowledge.__init__.py` exports~~ — the file exists but exports nothing (by design)

---

## Implementation Notes

### Pattern to Follow
```python
# The re-export shim pattern (thin module):
# pageindex/okf/ontology.py becomes:
from parrot.knowledge.okf.ontology import (
    ConceptType,
    RelationType,
    RelatesTo,
    SourceProvenance,
)

__all__ = [
    "ConceptType",
    "RelationType",
    "RelatesTo",
    "SourceProvenance",
]
```

### Key Constraints
- `ConceptType` values for existing members MUST remain identical strings
  (e.g., `"Section"`, `"Policy"`) to avoid breaking YAML frontmatter parsing.
- New graph-native type values use title-case: `"Symbol"`, `"Rationale"`, etc.
- `knowledge/__init__.py` intentionally does NOT re-export sub-packages (see
  existing pattern in `parrot/knowledge/__init__.py`).
- Test coverage: verify that `ConceptType("Section")` and
  `ConceptType("Symbol")` both work (string → enum round-trip).

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/ontology.py` — source to move
- `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/__init__.py` — re-export hub
- `packages/ai-parrot/tests/knowledge/pageindex/test_okf_ontology.py` — existing tests to verify

---

## Acceptance Criteria

- [ ] `from parrot.knowledge.okf.ontology import ConceptType` works
- [ ] `from parrot.knowledge.pageindex.okf import ConceptType` still works (re-export)
- [ ] `ConceptType` has 16 values (11 existing + 5 new)
- [ ] `RelationType` has 12 values (8 existing + 4 new)
- [ ] `ConceptType.SECTION.value == "Section"` (unchanged)
- [ ] `ConceptType.SYMBOL.value == "Symbol"` (new)
- [ ] All FEAT-238 tests pass: `pytest tests/knowledge/pageindex/test_okf_ontology.py -v`
- [ ] New tests pass: `pytest tests/knowledge/okf/test_ontology.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/knowledge/okf/`

---

## Test Specification

```python
# tests/knowledge/okf/test_ontology.py
import pytest
from parrot.knowledge.okf.ontology import (
    ConceptType,
    RelationType,
    RelatesTo,
    SourceProvenance,
)


class TestConceptType:
    def test_existing_values_unchanged(self):
        assert ConceptType.SECTION.value == "Section"
        assert ConceptType.POLICY.value == "Policy"
        assert ConceptType.GUIDELINE.value == "Guideline"

    def test_graph_native_values_exist(self):
        assert ConceptType.SYMBOL.value == "Symbol"
        assert ConceptType.RATIONALE.value == "Rationale"
        assert ConceptType.SKILL.value == "Skill"
        assert ConceptType.CONCEPT_NODE.value == "Concept"
        assert ConceptType.DOCUMENT_NODE.value == "Document"

    def test_total_count(self):
        assert len(ConceptType) == 16

    def test_string_round_trip(self):
        assert ConceptType("Symbol") == ConceptType.SYMBOL


class TestRelationType:
    def test_existing_values_unchanged(self):
        assert RelationType.REFERENCES.value == "references"
        assert RelationType.PART_OF.value == "part_of"

    def test_graph_edge_values_exist(self):
        assert RelationType.DEFINES.value == "defines"
        assert RelationType.MENTIONS.value == "mentions"
        assert RelationType.EXPLAINS.value == "explains"
        assert RelationType.CONTAINS.value == "contains"

    def test_total_count(self):
        assert len(RelationType) == 12


class TestReExportCompat:
    def test_pageindex_import_still_works(self):
        from parrot.knowledge.pageindex.okf import ConceptType as CT
        assert CT.SECTION.value == "Section"
        assert CT.SYMBOL.value == "Symbol"

    def test_pageindex_import_relates_to(self):
        from parrot.knowledge.pageindex.okf import RelatesTo as RT
        r = RT(concept="test-id")
        assert r.rel == RelationType.REFERENCES
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/graphindex-frontmatter.spec.md` for full context
2. **Check dependencies** — this task has no dependencies
3. **Verify the Codebase Contract** — confirm imports and line numbers are still accurate
4. **Create the `parrot/knowledge/okf/` package** first, then move types
5. **Test re-exports immediately** after creating the shim
6. **Run FEAT-238 tests** before marking complete
7. **Update status** in per-spec index → `"in-progress"` then `"done"`
8. **Move this file** to `tasks/completed/`

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-06-16
**Notes**: Created `parrot/knowledge/okf/` package with `ontology.py` containing
all 16 ConceptType values and 12 RelationType values. Made `pageindex/okf/ontology.py`
a thin re-export shim. All 39 tests pass (19 new + 20 updated FEAT-238 tests).

**Deviations from spec**: Updated 4 FEAT-238 tests in `test_okf_ontology.py` that
checked hardcoded enum counts (11 and 8). After extension, counts are 16 and 12.
Changed from exact set equality to `issubset()` for original value checks, and
updated count assertions to new values. This was necessary because the spec's
statement "all 20 FEAT-238 tests pass without modification" contradicts "extend
ConceptType to 16 values." Backward-compatible API (imports, existing values)
is fully preserved.
