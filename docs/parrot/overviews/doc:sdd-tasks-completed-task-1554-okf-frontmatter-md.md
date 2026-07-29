---
type: Wiki Overview
title: 'TASK-1554: Frontmatter Model & Projection (frontmatter.py)'
id: doc:sdd-tasks-completed-task-1554-okf-frontmatter-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The frontmatter is the **deterministic mirror** of the authoritative JSON
  node onto
relates_to:
- concept: mod:parrot.knowledge.pageindex.okf.frontmatter
  rel: mentions
- concept: mod:parrot.knowledge.pageindex.okf.ontology
  rel: mentions
---

# TASK-1554: Frontmatter Model & Projection (frontmatter.py)

**Feature**: FEAT-238 — OKF Knowledge Layer over PageIndex
**Spec**: `sdd/specs/okf-knowledge-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1552
**Assigned-to**: unassigned

---

## Context

The frontmatter is the **deterministic mirror** of the authoritative JSON node onto
each sidecar `.md` file. This module defines the `ConceptFrontmatter` Pydantic v2
model and the pure-function `project()` that renders it as YAML. The projection must
be **byte-deterministic**: the same JSON node → the same YAML bytes every time.

This is the core of the "single-writer, no-drift" guarantee (D1).

Implements: Spec §2 Frontmatter Projection, Spec §3 Module 3.

---

## Scope

- Implement `frontmatter.py` in `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/`:
  - `ConceptFrontmatter(BaseModel)` — Pydantic v2 model with fixed field order:
    `type`, `title`, `id` (concept_id), `node_id`, `resource`, `tags`, `timestamp`,
    `summary`, `relates_to`, `source`.
  - `project_frontmatter(node: dict, tree_name: str) -> str` — pure function that
    extracts OKF fields from a node dict and renders deterministic YAML frontmatter
    (with `---` delimiters).
  - `parse_frontmatter(text: str) -> ConceptFrontmatter` — parse YAML frontmatter
    from a sidecar string back into the model (for round-trip verification).
- Write unit tests proving byte-determinism.

**NOT in scope**: Writing sidecars to disk (TASK-1556), graph building (TASK-1555).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/frontmatter.py` | CREATE | ConceptFrontmatter model + project/parse |
| `packages/ai-parrot/tests/knowledge/pageindex/test_okf_frontmatter.py` | CREATE | Unit tests |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/__init__.py` | MODIFY | Add re-exports |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from pydantic import BaseModel, Field       # verified: used throughout codebase
import yaml                                 # pyyaml — already a project dependency

# From TASK-1552 (this task depends on it being complete):
from parrot.knowledge.pageindex.okf.ontology import (
    ConceptType,
    RelationType,
    RelatesTo,
    SourceProvenance,
)
```

### Existing Signatures to Use

```python
# ontology.py (created by TASK-1552)
class ConceptType(str, Enum): ...    # 11 values, "Section" is fallback
class RelationType(str, Enum): ...   # 8 values, "references" is default
class RelatesTo(BaseModel):
    concept: str
    rel: RelationType = RelationType.REFERENCES
class SourceProvenance(BaseModel):
    document: str
    pages: Optional[list[int]] = None
    url: Optional[str] = None
```

### Does NOT Exist

- ~~`parrot.knowledge.pageindex.okf.frontmatter`~~ — does not exist yet; this task creates it
- ~~`ConceptFrontmatter`~~ — does not exist anywhere
- ~~`NodeContentStore.save_with_frontmatter()`~~ — no such method

---

## Implementation Notes

### Pattern to Follow

```python
def project_frontmatter(node: dict, tree_name: str) -> str:
    """Pure function: node dict -> YAML frontmatter string.

    MUST be byte-deterministic: same node -> same bytes always.
    Field order is fixed (not alphabetical).
    """
    fm = ConceptFrontmatter(
        type=ConceptType(node.get("type", "Section")),
        title=node["title"],
        id=node["concept_id"],
        node_id=node["node_id"],
        resource=f"pageindex://{tree_name}/{node['concept_id']}",
        tags=sorted(node.get("categories", [])),
        timestamp=node.get("timestamp", ""),
        summary=node.get("summary", ""),
        relates_to=[RelatesTo(**r) for r in node.get("relates_to", [])],
        source=SourceProvenance(**node["source"]) if node.get("source") else None,
    )
    # Render with fixed field order, no sort_keys
    return _render_yaml(fm)
```

### Key Constraints

- **Byte-determinism**: Use `yaml.dump(sort_keys=False)` with a fixed field order
  defined by the model. Consider using a custom YAML representer or manual string
  building to guarantee order (PyYAML dict ordering depends on Python dict ordering,
  which is insertion-ordered in 3.7+, but `model_dump()` order must be controlled).
- **`summary` reuses the FEAT-199 embedding target text** (D11) — just copy from node.
- **`tags` sorted alphabetically** for determinism.
- **`source` is `Optional`** — omit the field entirely when `None` (don't emit `source: null`).
- **`relates_to` may be empty list** — emit as `relates_to: []` when empty.
- **Frontmatter delimiters**: output starts with `---\n` and ends with `---\n`.

---

## Acceptance Criteria

- [ ] `ConceptFrontmatter` model validates all expected fields
- [ ] `project_frontmatter(node, tree_name)` produces valid YAML frontmatter
- [ ] **Byte-deterministic**: calling `project_frontmatter` twice with the same node produces identical strings
- [ ] `parse_frontmatter(project_frontmatter(node, tree))` round-trips correctly
- [ ] Optional fields (`source`, `url`) are omitted when `None`, not emitted as `null`
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/pageindex/test_okf_frontmatter.py -v`
- [ ] No linting errors

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/pageindex/test_okf_frontmatter.py
import pytest
from parrot.knowledge.pageindex.okf.frontmatter import (
    ConceptFrontmatter,
    project_frontmatter,
    parse_frontmatter,
)
from parrot.knowledge.pageindex.okf.ontology import ConceptType


@pytest.fixture
def sample_node():
    return {
        "node_id": "0043",
        "concept_id": "playbooks/aws-incident-response",
        "type": "Playbook",
        "title": "AWS Incident Response",
        "summary": "Incident-response steps aligned to CC7.x",
        "categories": ["soc2", "aws"],
        "source": {"document": "guide.pdf", "pages": [43, 47]},
        "relates_to": [
            {"concept": "controls/nist-ir-4", "rel": "maps_to"}
        ],
    }


class TestProjectFrontmatter:
    def test_produces_valid_yaml(self, sample_node):
        result = project_frontmatter(sample_node, "soc2_hipaa")
        assert result.startswith("---\n")
        assert result.endswith("---\n")

    def test_byte_deterministic(self, sample_node):
        a = project_frontmatter(sample_node, "tree1")
        b = project_frontmatter(sample_node, "tree1")
        assert a == b

    def test_round_trip(self, sample_node):
        yaml_str = project_frontmatter(sample_node, "tree1")
        parsed = parse_frontmatter(yaml_str)
        reprojected = project_frontmatter(sample_node, "tree1")
        assert yaml_str == reprojected

    def test_optional_source_omitted(self):
        node = {
            "node_id": "0001",
            "concept_id": "test",
            "type": "Section",
            "title": "Test",
            "summary": "",
        }
        result = project_frontmatter(node, "tree")
        assert "source:" not in result or "source: null" not in result

    def test_resource_uses_concept_id(self, sample_node):
        result = project_frontmatter(sample_node, "soc2_hipaa")
        assert "pageindex://soc2_hipaa/playbooks/aws-incident-response" in result
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/okf-knowledge-layer.spec.md` for full context
2. **Check dependencies** — verify TASK-1552 (ontology) is complete
3. **Verify the Codebase Contract** — confirm ontology imports work
4. **Implement** `frontmatter.py` with the model and projection function
5. **Write tests** with special attention to byte-determinism
6. **Move this file** to `sdd/tasks/completed/` when done

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-15
**Notes**: Implemented ConceptFrontmatter Pydantic v2 model, project_frontmatter (byte-deterministic YAML), and parse_frontmatter. Added re-exports to __init__.py. All 20 tests pass. No linting errors.

**Deviations from spec**: none
