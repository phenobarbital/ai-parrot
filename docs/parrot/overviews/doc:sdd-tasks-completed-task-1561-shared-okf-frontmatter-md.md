---
type: Wiki Overview
title: 'TASK-1561: Move Frontmatter Engine to Shared OKF Package'
id: doc:sdd-tasks-completed-task-1561-shared-okf-frontmatter-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: After TASK-1560 creates the shared `parrot/knowledge/okf/` package with the
relates_to:
- concept: mod:parrot.knowledge.okf.frontmatter
  rel: mentions
- concept: mod:parrot.knowledge.okf.ontology
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.okf
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.okf.frontmatter
  rel: mentions
---

# TASK-1561: Move Frontmatter Engine to Shared OKF Package

**Feature**: FEAT-239 — GraphIndex OKF Frontmatter Projection
**Spec**: `sdd/specs/graphindex-frontmatter.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1560
**Assigned-to**: unassigned

---

## Context

After TASK-1560 creates the shared `parrot/knowledge/okf/` package with the
ontology types, this task moves the frontmatter engine (`ConceptFrontmatter`,
`project_frontmatter`, `parse_frontmatter`) into the shared package. The
PageIndex module becomes a thin re-export shim. Imports in `projection.py`
are updated to use the new canonical path.

Implements spec §3 Module 2 + Module 4 (frontmatter portion).

---

## Scope

- Move `ConceptFrontmatter`, `project_frontmatter`, `parse_frontmatter` from
  `pageindex/okf/frontmatter.py` into `knowledge/okf/frontmatter.py`.
- Replace `pageindex/okf/frontmatter.py` with a thin re-export shim.
- Update `pageindex/okf/projection.py` import: change
  `from parrot.knowledge.pageindex.okf.frontmatter import project_frontmatter`
  to `from parrot.knowledge.okf.frontmatter import project_frontmatter`.
- Update `pageindex/okf/__init__.py` if needed to import from new location.
- Update `knowledge/okf/__init__.py` to export frontmatter symbols.
- Write unit tests for frontmatter in `tests/knowledge/okf/test_frontmatter.py`.
- Verify all FEAT-238 frontmatter tests still pass.

**NOT in scope**: URI scheme (TASK-1562), GraphIndex projection (TASK-1563).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/okf/frontmatter.py` | CREATE | Frontmatter engine (moved) |
| `packages/ai-parrot/src/parrot/knowledge/okf/__init__.py` | MODIFY | Add frontmatter exports |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/frontmatter.py` | MODIFY | Thin re-export shim |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/__init__.py` | MODIFY | Update import source |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/projection.py` | MODIFY | Update import path (line 29) |
| `packages/ai-parrot/tests/knowledge/okf/test_frontmatter.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Current imports that MUST continue to work:
from parrot.knowledge.pageindex.okf import ConceptFrontmatter   # pageindex/okf/__init__.py:27
from parrot.knowledge.pageindex.okf import project_frontmatter  # pageindex/okf/__init__.py:28
from parrot.knowledge.pageindex.okf import parse_frontmatter    # pageindex/okf/__init__.py:29

# After TASK-1560, these also work:
from parrot.knowledge.okf.ontology import ConceptType           # knowledge/okf/ontology.py
from parrot.knowledge.okf.ontology import RelatesTo             # knowledge/okf/ontology.py
from parrot.knowledge.okf.ontology import SourceProvenance      # knowledge/okf/ontology.py

# NEW imports that must work after this task:
from parrot.knowledge.okf.frontmatter import ConceptFrontmatter   # (new)
from parrot.knowledge.okf.frontmatter import project_frontmatter  # (new)
from parrot.knowledge.okf.frontmatter import parse_frontmatter    # (new)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/okf/frontmatter.py
class ConceptFrontmatter(BaseModel):                # line 30
    type: ConceptType                               # line 31
    title: str                                      # line 32
    id: str                                         # line 33
    node_id: str                                    # line 34
    resource: str                                   # line 35
    tags: list[str]                                 # line 36
    timestamp: str                                  # line 37
    summary: str                                    # line 38
    relates_to: list[RelatesTo]                     # line 39
    source: Optional[SourceProvenance] = None       # line 40

def project_frontmatter(node: dict, tree_name: str) -> str:    # line 96
    # Accesses: node["concept_id"] (required), node.get("type"),
    # node.get("title"), node.get("node_id"), node.get("summary"),
    # node.get("categories") or node.get("tags"),
    # node.get("timestamp"), node.get("relates_to"), node.get("source")

def parse_frontmatter(text: str) -> ConceptFrontmatter:        # line 149

# packages/ai-parrot/src/parrot/knowledge/pageindex/okf/projection.py
# Line 29: from parrot.knowledge.pageindex.okf.frontmatter import project_frontmatter
# This import MUST be updated to:
# from parrot.knowledge.okf.frontmatter import project_frontmatter
```

### Does NOT Exist
- ~~`parrot.knowledge.okf.frontmatter`~~ — does not exist yet; this task creates it
- ~~`project_frontmatter(node: UniversalNode, ...)`~~ — the function takes a dict, NOT a UniversalNode
- ~~`ConceptFrontmatter.from_node()`~~ — no such factory method exists

---

## Implementation Notes

### Pattern to Follow
```python
# pageindex/okf/frontmatter.py becomes a thin shim:
from parrot.knowledge.okf.frontmatter import (
    ConceptFrontmatter,
    project_frontmatter,
    parse_frontmatter,
)

__all__ = [
    "ConceptFrontmatter",
    "project_frontmatter",
    "parse_frontmatter",
]
```

### Key Constraints
- The moved `frontmatter.py` must update its internal import of ontology types
  to use `from parrot.knowledge.okf.ontology import ...` (not the old pageindex path).
- `project_frontmatter()` logic must remain identical — no changes to the
  function body, only to import paths.
- `parse_frontmatter()` uses `yaml.safe_load` — ensure `pyyaml` import is preserved.
- The `projection.py` file imports only `project_frontmatter` from frontmatter
  (line 29). Update just that one import line.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/frontmatter.py` — source to move
- `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/projection.py:29` — import to update
- `packages/ai-parrot/tests/knowledge/pageindex/test_okf_frontmatter.py` — existing 20 tests

---

## Acceptance Criteria

- [ ] `from parrot.knowledge.okf.frontmatter import ConceptFrontmatter` works
- [ ] `from parrot.knowledge.okf.frontmatter import project_frontmatter` works
- [ ] `from parrot.knowledge.pageindex.okf import ConceptFrontmatter` still works
- [ ] `from parrot.knowledge.pageindex.okf import project_frontmatter` still works
- [ ] `project_frontmatter()` produces byte-identical output to the pre-move version
- [ ] `parse_frontmatter()` round-trips correctly
- [ ] All FEAT-238 frontmatter tests pass: `pytest tests/knowledge/pageindex/test_okf_frontmatter.py -v`
- [ ] New tests pass: `pytest tests/knowledge/okf/test_frontmatter.py -v`
- [ ] `projection.py` imports from `knowledge.okf.frontmatter` (not old path)

---

## Test Specification

```python
# tests/knowledge/okf/test_frontmatter.py
import pytest
from parrot.knowledge.okf.frontmatter import (
    ConceptFrontmatter,
    project_frontmatter,
    parse_frontmatter,
)
from parrot.knowledge.okf.ontology import ConceptType, RelationType, RelatesTo


class TestConceptFrontmatterModel:
    def test_create_with_required_fields(self):
        fm = ConceptFrontmatter(
            type=ConceptType.SECTION,
            title="Test",
            id="test-id",
            node_id="n-001",
            resource="knowledge://test/test-id",
            tags=[],
            timestamp="2026-06-16T00:00:00Z",
            summary="Test summary",
            relates_to=[],
        )
        assert fm.type == ConceptType.SECTION
        assert fm.id == "test-id"

    def test_create_with_graph_native_type(self):
        fm = ConceptFrontmatter(
            type=ConceptType.SYMBOL,
            title="Builder",
            id="builder-id",
            node_id="sym-001",
            resource="knowledge://graphindex/sym-001",
            tags=["python"],
            timestamp="2026-06-16T00:00:00Z",
            summary="A builder class",
            relates_to=[],
        )
        assert fm.type == ConceptType.SYMBOL


class TestProjectFrontmatter:
    def test_produces_yaml_block(self):
        node = {
            "concept_id": "test-concept",
            "type": "Section",
            "title": "Test Node",
            "node_id": "n-001",
            "summary": "A test node.",
            "categories": ["test"],
            "timestamp": "2026-06-16T00:00:00Z",
        }
        result = project_frontmatter(node, "test-tree")
        assert result.startswith("---\n")
        assert result.endswith("---\n")
        assert "type: Section" in result

    def test_byte_determinism(self):
        node = {
            "concept_id": "det-test",
            "type": "Policy",
            "title": "Determinism",
            "node_id": "n-002",
            "summary": "Check determinism.",
            "categories": ["b", "a"],
            "timestamp": "2026-06-16T00:00:00Z",
        }
        r1 = project_frontmatter(node, "tree")
        r2 = project_frontmatter(node, "tree")
        assert r1 == r2


class TestParseFrontmatter:
    def test_round_trip(self):
        node = {
            "concept_id": "rt-test",
            "type": "Control",
            "title": "Round Trip",
            "node_id": "n-003",
            "summary": "Round trip test.",
            "categories": [],
            "timestamp": "2026-06-16T00:00:00Z",
        }
        yaml_str = project_frontmatter(node, "tree")
        parsed = parse_frontmatter(yaml_str)
        assert parsed.id == "rt-test"
        assert parsed.type == ConceptType.CONTROL
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/graphindex-frontmatter.spec.md`
2. **Verify TASK-1560 is complete** — `parrot.knowledge.okf.ontology` must exist
3. **Move the frontmatter module** — copy logic, update internal imports to `knowledge.okf.ontology`
4. **Create the re-export shim** in `pageindex/okf/frontmatter.py`
5. **Update projection.py** import at line 29
6. **Run ALL FEAT-238 tests** before marking complete
7. **Commit and update index**

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-06-16
**Notes**: Created `parrot/knowledge/okf/frontmatter.py` with `ConceptFrontmatter`,
`project_frontmatter`, and `parse_frontmatter` (moved from pageindex, updated imports
to use `knowledge.okf.ontology`). Made `pageindex/okf/frontmatter.py` a thin shim.
Updated `projection.py` import. All 36 tests pass (19 new + 17 FEAT-238 tests).

**Deviations from spec**: None.
