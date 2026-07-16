---
type: Wiki Overview
title: 'TASK-1628: OKF Schema Extensions'
id: doc:sdd-tasks-completed-task-1628-okf-schema-extensions-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Extends existing OKF enums (ConceptType, RelationType) with wiki-specific
relates_to:
- concept: mod:parrot.knowledge.graphindex
  rel: mentions
- concept: mod:parrot.knowledge.okf.ontology
  rel: mentions
---

# TASK-1628: OKF Schema Extensions

**Feature**: FEAT-260 — LLM Wiki: Persistent Knowledge Base with PageIndex + GraphIndex
**Spec**: `sdd/specs/llmwiki-pageindex-graphindex.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1627
**Assigned-to**: unassigned

---

## Context

Extends existing OKF enums (ConceptType, RelationType) with wiki-specific
values and adds WIKI_PAGE to GraphIndex's NodeKind. Implements Spec §3 Module 2.

---

## Scope

- Add wiki-specific values to `ConceptType` enum: `WIKI_SUMMARY`,
  `WIKI_ENTITY`, `WIKI_COMPARISON`, `WIKI_SYNTHESIS`, `WIKI_OVERVIEW`
- Add wiki-specific values to `RelationType` enum: `SUMMARIZES`,
  `CONTRADICTS` (NOTE: `SUPERSEDES` already exists at line 75 — do NOT add it)
- Add `WIKI_PAGE` to GraphIndex's `NodeKind` enum
- Write tests verifying the new enum values

**NOT in scope**: OKFToolkit changes, wiki toolkit, lint extensions

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/okf/ontology.py` | MODIFY | Add wiki ConceptType and RelationType values |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/schema.py` | MODIFY | Add WIKI_PAGE to NodeKind |
| `tests/knowledge/wiki/test_schema_extensions.py` | CREATE | Tests for new enum values |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.okf.ontology import ConceptType, RelationType  # ontology.py:29, 60
from parrot.knowledge.graphindex import NodeKind  # schema.py:33
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/okf/ontology.py
class ConceptType(str, Enum):  # line 29
    SECTION = "Section"      # line 40
    # ... 14 more values ...
    CONCEPT_NODE = "Concept"  # line 56
    DOCUMENT_NODE = "Document"  # line 57
    # ← ADD new wiki values AFTER line 57

class RelationType(str, Enum):  # line 60
    REFERENCES = "references"  # line 71
    SUPERSEDES = "supersedes"  # line 75  ← ALREADY EXISTS
    SUPERSEDED_BY = "superseded_by"  # line 76
    # ... more values ...
    EXTENDS = "extends"  # line 87
    # ← ADD SUMMARIZES, CONTRADICTS AFTER line 87

# packages/ai-parrot/src/parrot/knowledge/graphindex/schema.py
class NodeKind(str, Enum):  # line 33
    DOCUMENT = "document"   # line 45
    SECTION = "section"     # line 46
    SYMBOL = "symbol"       # line 47
    CONCEPT = "concept"     # line 48
    RATIONALE = "rationale" # line 49
    SKILL = "skill"         # line 50
    # ← ADD WIKI_PAGE AFTER line 50
```

### Does NOT Exist

- ~~`RelationType.SUMMARIZES`~~ — does not exist yet; add it
- ~~`RelationType.CONTRADICTS`~~ — does not exist yet; add it
- ~~`ConceptType.WIKI_SUMMARY`~~ — does not exist yet; add it
- ~~`NodeKind.WIKI_PAGE`~~ — does not exist yet; add it
- **`RelationType.SUPERSEDES` ALREADY EXISTS** (line 75) — do NOT add again

---

## Implementation Notes

### Key Constraints

- Enum values must use the same string-value pattern as existing entries
- ConceptType values use Title Case (e.g., "Wiki Summary")
- RelationType values use snake_case (e.g., "summarizes")
- NodeKind values use lowercase (e.g., "wiki_page")
- Do NOT reorder existing enum values — append only

---

## Acceptance Criteria

- [ ] ConceptType has 5 new wiki values (21 total)
- [ ] RelationType has 2 new values (15 total); SUPERSEDES NOT duplicated
- [ ] NodeKind has WIKI_PAGE (7 total)
- [ ] All tests pass: `pytest tests/knowledge/wiki/test_schema_extensions.py -v`
- [ ] Existing tests still pass: `pytest tests/ -k "okf or graphindex" --tb=short`

---

## Test Specification

```python
import pytest
from parrot.knowledge.okf.ontology import ConceptType, RelationType
from parrot.knowledge.graphindex import NodeKind

class TestWikiConceptTypes:
    def test_wiki_summary_exists(self):
        assert ConceptType.WIKI_SUMMARY.value == "Wiki Summary"

    def test_wiki_entity_exists(self):
        assert ConceptType.WIKI_ENTITY.value == "Wiki Entity"

    def test_existing_values_unchanged(self):
        assert ConceptType.SECTION.value == "Section"
        assert ConceptType.DOCUMENT_NODE.value == "Document"

class TestWikiRelationTypes:
    def test_summarizes_exists(self):
        assert RelationType.SUMMARIZES.value == "summarizes"

    def test_contradicts_exists(self):
        assert RelationType.CONTRADICTS.value == "contradicts"

    def test_supersedes_still_exists(self):
        assert RelationType.SUPERSEDES.value == "supersedes"

class TestNodeKindWikiPage:
    def test_wiki_page_exists(self):
        assert NodeKind.WIKI_PAGE.value == "wiki_page"

    def test_existing_kinds_unchanged(self):
        assert NodeKind.DOCUMENT.value == "document"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/llmwiki-pageindex-graphindex.spec.md` §3 Module 2
2. **Check dependencies** — TASK-1627 must be completed
3. **Read** `okf/ontology.py` and `graphindex/schema.py` to verify line numbers
4. **Append** new values to existing enums — do NOT reorder
5. **Verify** existing tests still pass after modifications

---

## Completion Note

*(Agent fills this in when done)*
