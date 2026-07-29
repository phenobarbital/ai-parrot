---
type: Wiki Overview
title: 'TASK-1552: Controlled Type & Relation Vocabulary (ontology.py)'
id: doc:sdd-tasks-completed-task-1552-okf-ontology-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This is the foundational leaf module for the OKF Knowledge Layer. Every other
relates_to:
- concept: mod:parrot.knowledge.pageindex
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.okf
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.okf.ontology
  rel: mentions
---

# TASK-1552: Controlled Type & Relation Vocabulary (ontology.py)

**Feature**: FEAT-238 — OKF Knowledge Layer over PageIndex
**Spec**: `sdd/specs/okf-knowledge-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the foundational leaf module for the OKF Knowledge Layer. Every other
module in FEAT-238 imports from `ontology.py` — it defines the controlled type
vocabulary (`ConceptType`), the typed edge vocabulary (`RelationType`), and the
Pydantic v2 data models (`SourceProvenance`, `RelatesTo`) that the rest of the
layer uses.

Implements: Spec §2 Data Models, Spec §3 Module 1.

---

## Scope

- Create the `okf/` subpackage under `packages/ai-parrot/src/parrot/knowledge/pageindex/`.
- Implement `ontology.py` with:
  - `ConceptType(str, Enum)` — controlled ontological vocabulary for OKF node types.
    Values: `Section` (structural fallback), `Policy`, `Control`, `Safeguard`,
    `Evidence`, `Playbook`, `Procedure`, `Standard`, `Framework`, `Regulation`,
    `Guideline`.
  - `RelationType(str, Enum)` — typed edge vocabulary.
    Values: `references` (default for untyped prose links), `maps_to`, `satisfies`,
    `satisfied_by`, `supersedes`, `superseded_by`, `implements`, `part_of`.
  - `RelatesTo(BaseModel)` — a typed edge: `concept: str`, `rel: RelationType`.
  - `SourceProvenance(BaseModel)` — per-node provenance: `document: str`,
    `pages: Optional[list[int]]`, `url: Optional[str]`.
- Create `okf/__init__.py` that re-exports all public symbols.
- Write unit tests.

**NOT in scope**: `ConceptFrontmatter` model (TASK-1554), graph logic (TASK-1555),
tool definitions (TASK-1558).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/__init__.py` | CREATE | Subpackage init, re-exports public symbols |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/ontology.py` | CREATE | Enums + Pydantic models |
| `packages/ai-parrot/tests/knowledge/pageindex/test_okf_ontology.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from enum import Enum                       # stdlib
from typing import Optional                 # stdlib
from pydantic import BaseModel, Field       # verified: used throughout parrot codebase
```

### Existing Signatures to Use

No existing signatures needed — this is a leaf module creating new types.

### Does NOT Exist

- ~~`parrot.knowledge.pageindex.okf`~~ — does not exist yet; this task creates it
- ~~`parrot.knowledge.pageindex.ontology`~~ — no ontology module exists at the pageindex level
- ~~`parrot.knowledge.pageindex.types`~~ — no types module exists
- ~~`ConceptType`~~ — does not exist anywhere in the codebase

---

## Implementation Notes

### Pattern to Follow

```python
# Follow the str-Enum pattern used elsewhere in parrot
class ConceptType(str, Enum):
    """Controlled ontological vocabulary for OKF node types (D9)."""
    SECTION = "Section"
    POLICY = "Policy"
    # ...
```

### Key Constraints

- Use `str, Enum` so values serialize naturally to JSON/YAML strings.
- `Section` is the structural fallback when LLM classification is unavailable.
- `RelationType.REFERENCES` is the default for untyped prose link fallback.
- All Pydantic models must use v2 style (no `Config` inner class — use `model_config`).
- `SourceProvenance.pages` is `Optional[list[int]]` — `[start_page, end_page]` from
  the node's `start_index`/`end_index` fields.

---

## Acceptance Criteria

- [ ] `ConceptType` enum has all 11 values from the spec
- [ ] `RelationType` enum has all 8 values from the spec
- [ ] `RelatesTo` model validates correctly with `concept` and `rel` fields
- [ ] `SourceProvenance` model validates correctly
- [ ] `from parrot.knowledge.pageindex.okf.ontology import ConceptType, RelationType, RelatesTo, SourceProvenance` works
- [ ] `from parrot.knowledge.pageindex.okf import ConceptType` works (re-export)
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/pageindex/test_okf_ontology.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/knowledge/pageindex/okf/`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/pageindex/test_okf_ontology.py
import pytest
from parrot.knowledge.pageindex.okf.ontology import (
    ConceptType,
    RelationType,
    RelatesTo,
    SourceProvenance,
)


class TestConceptType:
    def test_all_values_present(self):
        expected = {
            "Section", "Policy", "Control", "Safeguard", "Evidence",
            "Playbook", "Procedure", "Standard", "Framework",
            "Regulation", "Guideline",
        }
        assert {t.value for t in ConceptType} == expected

    def test_section_is_fallback(self):
        assert ConceptType.SECTION == "Section"

    def test_str_serialization(self):
        assert str(ConceptType.PLAYBOOK) == "ConceptType.PLAYBOOK"
        assert ConceptType.PLAYBOOK.value == "Playbook"


class TestRelationType:
    def test_all_values_present(self):
        expected = {
            "references", "maps_to", "satisfies", "satisfied_by",
            "supersedes", "superseded_by", "implements", "part_of",
        }
        assert {r.value for r in RelationType} == expected

    def test_references_is_default(self):
        assert RelationType.REFERENCES == "references"


class TestRelatesTo:
    def test_valid_edge(self):
        edge = RelatesTo(concept="controls/nist-ir-4", rel=RelationType.MAPS_TO)
        assert edge.concept == "controls/nist-ir-4"
        assert edge.rel == RelationType.MAPS_TO

    def test_default_rel_is_references(self):
        edge = RelatesTo(concept="some-concept")
        assert edge.rel == RelationType.REFERENCES

    def test_rejects_missing_concept(self):
        with pytest.raises(Exception):
            RelatesTo()


class TestSourceProvenance:
    def test_full_provenance(self):
        src = SourceProvenance(
            document="guide.pdf", pages=[43, 47], url="https://example.com"
        )
        assert src.document == "guide.pdf"
        assert src.pages == [43, 47]

    def test_minimal_provenance(self):
        src = SourceProvenance(document="guide.pdf")
        assert src.pages is None
        assert src.url is None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/okf-knowledge-layer.spec.md` for full context
2. **Check dependencies** — none; this is the first task
3. **Verify the Codebase Contract** — confirm the `okf/` subpackage directory does not yet exist
4. **Create** `okf/__init__.py` and `okf/ontology.py`
5. **Write tests** and verify they pass
6. **Update status** in `sdd/tasks/index/okf-knowledge-layer.json` → `"in-progress"`
7. **Move this file** to `sdd/tasks/completed/` when done
8. **Update index** → `"done"`

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-15
**Notes**: Created `okf/__init__.py` and `okf/ontology.py` with ConceptType (11 values), RelationType (8 values), RelatesTo and SourceProvenance Pydantic v2 models. All 20 tests pass. No linting errors.

**Deviations from spec**: none
