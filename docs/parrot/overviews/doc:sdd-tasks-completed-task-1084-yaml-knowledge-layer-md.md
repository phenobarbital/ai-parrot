---
type: Wiki Overview
title: 'TASK-1084: YAML Knowledge Layer'
id: doc:sdd-tasks-completed-task-1084-yaml-knowledge-layer-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'from parrot.knowledge.ontology.merger import OntologyMerger # verified:
  merger.py:26'
relates_to:
- concept: mod:parrot.knowledge.ontology.merger
  rel: mentions
- concept: mod:parrot.knowledge.ontology.parser
  rel: mentions
- concept: mod:parrot.knowledge.ontology.schema
  rel: mentions
- concept: mod:parrot.knowledge.ontology.tenant
  rel: mentions
---

# TASK-1084: YAML Knowledge Layer

**Feature**: FEAT-159 — Concept-Document Authority Layer
**Spec**: `sdd/specs/concept-document-authority.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> Module 1 of the spec. This is the foundational YAML layer that declares `Document` and `Concept`
> as first-class ontology entities, `covers_topic` and `is_a` as ontology relations, and the
> `authoritative_doc_for_topic` traversal pattern. The YAML is loaded through the existing
> `OntologyMerger` — no code changes to the parser or merger. Also introduces the per-tenant
> `authority/{tenant_id}.yaml` directory convention.

---

## Scope

- Create `packages/ai-parrot/src/parrot/knowledge/ontology/defaults/knowledge.ontology.yaml` with the full YAML content from spec §2 (entities: Document, Concept; relations: covers_topic, is_a; traversal: authoritative_doc_for_topic).
- Add a golden test that loads the new YAML through `OntologyMerger.merge()` alongside the existing `base.ontology.yaml` and verifies entities, relations, and traversal patterns round-trip without loss.
- Document the `{ontology_dir}/authority/{tenant_id}.yaml` convention for per-tenant authority edge files.
- Add a test that verifies per-tenant authority YAML is picked up when placed in the expected directory.

**NOT in scope**: Implementing the `hybrid_concept_match` resolver (TASK-1088), implementing `search_documents_scoped` (TASK-1089), the concept embedding pipeline (TASK-1085), or edge ingestion into ArangoDB.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/defaults/knowledge.ontology.yaml` | CREATE | Knowledge layer YAML with Document, Concept, covers_topic, is_a, authoritative_doc_for_topic |
| `packages/ai-parrot/tests/knowledge/test_knowledge_yaml.py` | CREATE | Golden tests for YAML loading and merger round-trip |
| `packages/ai-parrot/tests/knowledge/fixtures/concept_authority/` | CREATE | Test fixtures directory |
| `packages/ai-parrot/tests/knowledge/fixtures/concept_authority/authority/acme.yaml` | CREATE | Sample per-tenant authority YAML fixture |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.

### Verified Imports
```python
from parrot.knowledge.ontology.merger import OntologyMerger  # verified: merger.py:26
from parrot.knowledge.ontology.schema import MergedOntology  # verified: schema.py (via merger import)
from parrot.knowledge.ontology.tenant import TenantOntologyManager  # verified: tenant.py:18
from parrot.knowledge.ontology.parser import OntologyParser  # used by merger internally
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/ontology/merger.py:26
class OntologyMerger:
    def merge(self, yaml_paths: list[Path]) -> MergedOntology:  # line 51
        ...
    def merge_definitions(self, ...):  # line 99

# packages/ai-parrot/src/parrot/knowledge/ontology/tenant.py:18
class TenantOntologyManager:
    def __init__(self, ontology_dir, base_file, domains_dir, clients_dir, ...):  # line 37
    def resolve(self, tenant_id: str, domain: str | None = None) -> TenantContext:  # line 74 — SYNC, not async
```

### Existing YAML Structure
```
packages/ai-parrot/src/parrot/knowledge/ontology/defaults/
├── base.ontology.yaml    # existing base ontology
├── domains/              # domain ontologies
└── __init__.py
```

### Does NOT Exist
- ~~An `authority/` directory inside ontology defaults~~ — does NOT exist; this task creates the convention
- ~~`OntologyMerger` supporting an `edges:` top-level key for data loading~~ — the merger merges schema definitions (entities, relations, patterns), NOT edge instances. See Open Question §8.
- ~~`EntityResolver`, `ToolCallDispatcher`, `ContextEnvelope`~~ — added by FEAT-158, not yet on `dev`. The YAML `entity_extraction` and `tool_call` blocks reference FEAT-158 features; this task creates the YAML, FEAT-158 wires it.
- ~~`TenantOntologyManager.resolve()` loading from `authority/` directory~~ — does NOT exist; Module 3 (TASK-1086) adds this loader path.

---

## Implementation Notes

### Pattern to Follow
The new YAML file follows the same structure as `base.ontology.yaml`. Use `name: knowledge` and `extends: base` so the merger layers it on top.

### Key Constraints
- The YAML must be valid for `OntologyMerger.merge()` — test by calling merge with `[base.ontology.yaml, knowledge.ontology.yaml]`.
- The traversal pattern `authoritative_doc_for_topic` uses `entity_extraction` and `tool_call` blocks that depend on FEAT-158; the YAML is valid schema but won't be *executed* until FEAT-158 lands. Tests should verify the YAML loads and round-trips, not that the traversal executes.
- The per-tenant authority YAML test can use `TenantOntologyManager` with a tmp_path ontology directory that includes the authority subdirectory.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/ontology/defaults/base.ontology.yaml` — existing YAML structure to follow
- `packages/ai-parrot/src/parrot/knowledge/ontology/merger.py` — merger that loads YAML
- `packages/ai-parrot/src/parrot/knowledge/ontology/parser.py` — parser used by merger

---

## Acceptance Criteria

- [ ] `knowledge.ontology.yaml` exists at `packages/ai-parrot/src/parrot/knowledge/ontology/defaults/knowledge.ontology.yaml`
- [ ] `OntologyMerger.merge([base.ontology.yaml, knowledge.ontology.yaml])` returns a `MergedOntology` with `Document` and `Concept` entities, `covers_topic` and `is_a` relations, and `authoritative_doc_for_topic` traversal pattern
- [ ] Entity properties match spec §2 (all fields, types, defaults for Document and Concept)
- [ ] Relation properties match spec §2 (covers_topic with authority enum, is_a)
- [ ] Traversal pattern includes trigger_intents, entity_extraction, query_template, post_action, and tool_call blocks
- [ ] Sample per-tenant authority YAML loads without errors
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/test_knowledge_yaml.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/knowledge/ontology/defaults/`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/test_knowledge_yaml.py
import pytest
from pathlib import Path
from parrot.knowledge.ontology.merger import OntologyMerger


class TestKnowledgeYAML:
    def test_knowledge_yaml_loads_and_merges(self):
        """YAML round-trips through OntologyMerger; new entities/relations/pattern appear."""
        merger = OntologyMerger()
        defaults_dir = Path(__file__).resolve().parents[3] / "src" / "parrot" / "knowledge" / "ontology" / "defaults"
        base = defaults_dir / "base.ontology.yaml"
        knowledge = defaults_dir / "knowledge.ontology.yaml"
        merged = merger.merge([base, knowledge])

        assert "Document" in merged.entities
        assert "Concept" in merged.entities
        assert "covers_topic" in merged.relations
        assert "is_a" in merged.relations
        assert "authoritative_doc_for_topic" in merged.traversal_patterns

    def test_document_entity_properties(self):
        """Document entity has all specified properties."""
        # Verify document_id, title, doc_type, version, effective_date,
        # is_current, authority_score, pageindex_tree_id, language
        ...

    def test_concept_entity_properties(self):
        """Concept entity has concept_id, label, synonyms, description, domain."""
        ...

    def test_covers_topic_relation_properties(self):
        """covers_topic has authority enum, confidence, asserted_by."""
        ...

    def test_traversal_pattern_structure(self):
        """authoritative_doc_for_topic has trigger_intents, entity_extraction, query_template, post_action."""
        ...

    def test_authority_per_tenant_yaml_loaded(self, tmp_path):
        """Per-tenant authority/<tenant>.yaml is loadable through merger."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — this task has no dependencies
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/concept-document-authority.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1084-yaml-knowledge-layer.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
