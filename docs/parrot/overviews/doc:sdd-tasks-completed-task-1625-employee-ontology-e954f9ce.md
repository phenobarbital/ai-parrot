---
type: Wiki Overview
title: 'TASK-1625: Employee Ontology Integration Smoke Test'
id: doc:sdd-tasks-completed-task-1625-employee-ontology-smoke-test-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: After adding the Employee entity to `knowledge.ontology.yaml` (TASK-1624),
  this task
relates_to:
- concept: mod:parrot.knowledge.ontology.merger
  rel: mentions
- concept: mod:parrot.knowledge.ontology.parser
  rel: mentions
- concept: mod:parrot.knowledge.ontology.schema
  rel: mentions
---

# TASK-1625: Employee Ontology Integration Smoke Test

**Feature**: FEAT-255 — Ontology RAG + Employee Knowledge Base
**Spec**: `sdd/specs/ontology-rag-kb.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1624
**Assigned-to**: unassigned

---

## Context

After adding the Employee entity to `knowledge.ontology.yaml` (TASK-1624), this task
adds a schema-level smoke test that verifies the merged ontology is internally consistent
without requiring a live ArangoDB or Redis instance.

---

## Scope

- Create `tests/knowledge/test_employee_ontology_smoke.py`
- Test that `knowledge.ontology.yaml` loads via `OntologyParser`
- Test that merging base + knowledge ontologies produces a valid `MergedOntology`
- Assert Employee entity present with required properties
- Assert `reports_to` relation references Employee on both ends

**NOT in scope**: ArangoDB integration, RAG pipeline end-to-end test.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/knowledge/test_employee_ontology_smoke.py` | CREATE | Schema-level smoke tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.ontology.parser import OntologyParser
from parrot.knowledge.ontology.merger import OntologyMerger
from parrot.knowledge.ontology.schema import MergedOntology
```

---

## Acceptance Criteria

- [ ] `pytest packages/ai-parrot/tests/knowledge/test_employee_ontology_smoke.py -v` passes
- [ ] No ArangoDB or Redis required for the test suite

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/test_employee_ontology_smoke.py
import pytest
from parrot.knowledge.ontology.parser import OntologyParser
from parrot.knowledge.ontology.merger import OntologyMerger


@pytest.fixture
def base_ontology():
    return OntologyParser.load_default("base")


@pytest.fixture
def knowledge_ontology():
    return OntologyParser.load_default("knowledge")


@pytest.fixture
def merged(base_ontology, knowledge_ontology):
    return OntologyMerger.merge([base_ontology, knowledge_ontology])


class TestEmployeeOntologySmoke:
    def test_knowledge_yaml_loads(self, knowledge_ontology):
        assert knowledge_ontology is not None
        assert knowledge_ontology.name == "knowledge"

    def test_employee_entity_present(self, merged):
        assert "Employee" in merged.entities

    def test_employee_required_properties(self, merged):
        emp = merged.entities["Employee"]
        prop_names = [list(p.keys())[0] for p in emp.properties]
        assert "employee_id" in prop_names
        assert "name" in prop_names
        assert "email" in prop_names

    def test_reports_to_relation(self, merged):
        assert "reports_to" in merged.relations
        rel = merged.relations["reports_to"]
        assert rel.from_entity == "Employee"
        assert rel.to_entity == "Employee"

    def test_merge_integrity(self, merged):
        # Relation endpoints must reference existing entities
        for rel_name, rel in merged.relations.items():
            assert rel.from_entity in merged.entities, \
                f"Relation {rel_name}: from={rel.from_entity} not in entities"
            assert rel.to_entity in merged.entities, \
                f"Relation {rel_name}: to={rel.to_entity} not in entities"
```

---

## Completion Note

Implemented `packages/ai-parrot/tests/knowledge/test_employee_ontology_smoke.py` with
5 smoke tests covering:

- `test_knowledge_yaml_loads` — knowledge.ontology.yaml loads with name="knowledge"
- `test_employee_entity_present` — Employee entity appears in the merged ontology
- `test_employee_required_properties` — employee_id, name, email all present
- `test_reports_to_relation` — reports_to is Employee→Employee on both ends
- `test_merge_integrity` — all relation endpoints reference existing entities

**Codebase Contract correction**: The task's test scaffold used
`OntologyParser.load_default("base"/"knowledge")` (non-existent static method) and
`OntologyMerger.merge([definitions])` (incorrect — merge() takes paths, not definitions).
Corrected to `OntologyParser.load(path)` and `OntologyMerger().merge_definitions([...])`.

All 5 tests pass. No ArangoDB or Redis required. `ruff check` clean.
