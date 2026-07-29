---
type: Wiki Overview
title: 'TASK-1253: Core Schema — Universal Node/Edge Models and Meta-Ontology'
id: doc:sdd-tasks-completed-task-1253-graphindex-core-schema-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This is the **prerequisite foundation** for all other GraphIndex tasks. It
  defines the `UniversalNode`, `UniversalEdge`, and supporting Pydantic models that
  form the contract between all pipeline stages. It also defines the universal meta-ontology
  (6 entity types, 5 relation type
relates_to:
- concept: mod:parrot.knowledge.graphindex
  rel: mentions
- concept: mod:parrot.knowledge.graphindex.schema
  rel: mentions
- concept: mod:parrot.knowledge.ontology.schema
  rel: mentions
---

# TASK-1253: Core Schema — Universal Node/Edge Models and Meta-Ontology

**Feature**: FEAT-187 — GraphIndex — Structured Knowledge Graph Indexing
**Spec**: `sdd/specs/graphindex.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the **prerequisite foundation** for all other GraphIndex tasks. It defines the `UniversalNode`, `UniversalEdge`, and supporting Pydantic models that form the contract between all pipeline stages. It also defines the universal meta-ontology (6 entity types, 5 relation types) that extends the existing `MergedOntology` system.

Implements: Spec §2 Data Models, §3 Module 1.

---

## Scope

- Implement `UniversalNode`, `UniversalEdge`, `Provenance`, `NodeKind`, `EdgeKind` Pydantic models
- Implement `SourceConfig` (input configuration for what to index), `BuildResult`, `IngestResult` models
- Define the universal meta-ontology as a YAML file or programmatic `MergedOntology`-compatible definition with:
  - 6 entity types: `document`, `section`, `symbol`, `concept`, `rationale`, `skill`
  - 5 relation types: `contains`, `references`, `defines`, `mentions`, `explains`
- Create the `parrot.knowledge.graphindex` package with `__init__.py`
- Enforce constraint: `confidence` must be set iff `provenance == INFERRED`
- Write unit tests for all models

**NOT in scope**: extractors, embedding, graph assembly, persistence, analytics, toolkit

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/__init__.py` | CREATE | Package init with public exports |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/schema.py` | CREATE | UniversalNode, UniversalEdge, enums, SourceConfig, BuildResult, IngestResult |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/meta_ontology.py` | CREATE | Universal meta-ontology definition compatible with MergedOntology |
| `packages/ai-parrot/tests/knowledge/graphindex/__init__.py` | CREATE | Test package init |
| `packages/ai-parrot/tests/knowledge/graphindex/test_schema.py` | CREATE | Unit tests for all models |
| `packages/ai-parrot/tests/knowledge/graphindex/test_meta_ontology.py` | CREATE | Tests for meta-ontology definition |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.ontology.schema import (
    TenantContext,       # verified: packages/ai-parrot/src/parrot/knowledge/ontology/schema.py
    MergedOntology,      # entities: dict[str, EntityDef], relations: dict[str, RelationDef]
    EntityDef,           # collection, key_field, properties, vectorize, extend
    RelationDef,         # from_entity (alias "from"), to_entity (alias "to"), edge_collection
)
from pydantic import BaseModel, Field, field_validator
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/ontology/schema.py
class EntityDef(BaseModel):
    collection: str | None = None
    source: str | None = None
    key_field: str | None = None
    properties: list[dict[str, PropertyDef]] = Field(default_factory=list)
    vectorize: list[str] = Field(default_factory=list)
    extend: bool = False

class RelationDef(BaseModel):
    from_entity: str = Field(alias="from")
    to_entity: str = Field(alias="to")
    edge_collection: str
    properties: list[dict[str, PropertyDef]] = Field(default_factory=list)
    discovery: DiscoveryConfig = Field(default_factory=DiscoveryConfig)

class MergedOntology(BaseModel):
    name: str
    version: str
    entities: dict[str, EntityDef]
    relations: dict[str, RelationDef]
    traversal_patterns: dict[str, TraversalPattern]
    layers: list[str]
    merge_timestamp: datetime
    def get_entity_collections(self) -> list[str]: ...
    def get_edge_collections(self) -> list[str]: ...
```

### Does NOT Exist
- ~~`parrot.knowledge.graphindex`~~ — does not exist yet; this task creates it
- ~~`Ontology` class~~ — actual name is `MergedOntology`
- ~~`Entity` class~~ — actual name is `EntityDef`
- ~~`Relation` class~~ — actual name is `RelationDef`

---

## Implementation Notes

### Pattern to Follow
```python
# Follow the existing enum + Pydantic model pattern from parrot.knowledge.ontology.schema
class Provenance(str, Enum):
    EXTRACTED = "extracted"
    INFERRED = "inferred"
    AMBIGUOUS = "ambiguous"

class UniversalNode(BaseModel):
    node_id: str
    kind: NodeKind
    title: str
    source_uri: str
    content_ref: Optional[str] = None
    summary: Optional[str] = None
    embedding_ref: Optional[str] = None
    domain_tags: dict = Field(default_factory=dict)
    parent_id: Optional[str] = None
    provenance: Provenance = Provenance.EXTRACTED
```

### Key Constraints
- Async-first, type-hinted, Pydantic v2 models
- Google-style docstrings
- `confidence` field on `UniversalEdge` must be `None` unless `provenance == INFERRED`
- Meta-ontology must be additive — must not conflict with existing tenant ontologies

---

## Acceptance Criteria

- [ ] `UniversalNode` and `UniversalEdge` models validate correctly
- [ ] `confidence` constraint enforced: set iff `provenance == INFERRED`
- [ ] All 6 `NodeKind` and 5 `EdgeKind` enums defined
- [ ] `SourceConfig`, `BuildResult`, `IngestResult` models defined
- [ ] Meta-ontology produces 6 EntityDef + 5 RelationDef entries
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/graphindex/ -v`
- [ ] Import works: `from parrot.knowledge.graphindex.schema import UniversalNode, UniversalEdge`

---

## Test Specification

```python
import pytest
from parrot.knowledge.graphindex.schema import (
    UniversalNode, UniversalEdge, Provenance, NodeKind, EdgeKind,
)

class TestUniversalNode:
    def test_valid_node(self):
        node = UniversalNode(node_id="n1", kind=NodeKind.SYMBOL, title="func", source_uri="file.py")
        assert node.provenance == Provenance.EXTRACTED

    def test_default_domain_tags(self):
        node = UniversalNode(node_id="n1", kind=NodeKind.DOCUMENT, title="doc", source_uri="doc.pdf")
        assert node.domain_tags == {}

class TestUniversalEdge:
    def test_inferred_requires_confidence(self):
        edge = UniversalEdge(source_id="a", target_id="b", kind=EdgeKind.MENTIONS,
                             provenance=Provenance.INFERRED, confidence=0.85)
        assert edge.confidence == 0.85

    def test_extracted_no_confidence(self):
        edge = UniversalEdge(source_id="a", target_id="b", kind=EdgeKind.CONTAINS)
        assert edge.confidence is None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/graphindex.spec.md` for full context
2. **Check dependencies** — this task has no dependencies
3. **Verify the Codebase Contract** — confirm `EntityDef`, `RelationDef`, `MergedOntology` signatures
4. **Update status** in `sdd/tasks/index/graphindex.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1253-graphindex-core-schema.md`
8. **Update index** → `"done"`

---

## Completion Note

Implemented all models as specified:
- `UniversalNode`, `UniversalEdge`, `Provenance`, `NodeKind`, `EdgeKind` enums with full Pydantic v2 validation
- `confidence` iff `provenance == INFERRED` constraint enforced via `model_validator`
- `SourceConfig`, `BuildResult`, `IngestResult` models defined
- `meta_ontology.py` defines 6 `EntityDef` entries (prefixed `gi_`) and 5 `RelationDef` entries
- Helper dicts `KIND_TO_COLLECTION`, `COLLECTION_TO_KIND`, `EDGE_KIND_TO_COLLECTION` for persistence routing
- 34 unit tests — all pass
